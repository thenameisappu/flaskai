import pandas as pd
from db import get_connection
from rdkit import Chem
from rdkit.Chem.inchi import MolToInchiKey
from rdkit.Chem import AllChem, DataStructs
import re
import warnings

from normalization import normalize_chemical_name

warnings.filterwarnings('ignore', category=UserWarning, module='pandas')

def check_rdkit_extension(conn):
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_extension WHERE extname='rdkit';")
        exists = cur.fetchone() is not None
        cur.close()
        return exists
    except Exception:
        return False


def expand_greek_variants(text):
    if not text:
        return []
    variants = [text]
    # Simple greek replacements keeping the rest of the string intact
    greek_forward = {'alpha': 'α', 'beta': 'β', 'gamma': 'γ', 'delta': 'δ', 'epsilon': 'ε'}
    greek_backward = {v: k for k, v in greek_forward.items()}
    mapping = {**greek_forward, **greek_backward}
    
    for k, v in mapping.items():
        if k in text.lower():
            pattern = re.compile(re.escape(k), re.IGNORECASE)
            variants.append(pattern.sub(v, text))
            
    return list(set(variants))

def search_molecules(
    smiles=None,
    iupacName=None,
    casNumber=None,
    altName=None,
    cid=None,
    minWeight=None,
    maxWeight=None,
    search=None,
    exact=False,
    search_mode="",
    similarity_threshold=0.7
):

    try:

        conn = get_connection()
        has_extension = check_rdkit_extension(conn)

        query = "SELECT * FROM molecules WHERE 1=1"
        params = []

        # =========================
        # UNIFIED NORMALIZED SEARCH
        # =========================
        if search:

            # 1. Add preprocessing (normalization) layer before any comparison
            normalized_query = normalize_chemical_name(search)
            
            # The unified Global Text Field Searches across all columns
            conditions = """
                casnumber = %s
                OR casnumber ILIKE %s
                OR array_to_string(alternativenames, ',') ILIKE %s
                OR smiles ILIKE %s
                OR inchikey ILIKE %s
                OR cid::text ILIKE %s
                OR molweight::text ILIKE %s
            """

            # Params carefully aligned
            params.extend([
                search, f"%{search}%", normalized_query, normalized_query,
                f"%{normalized_query}%", f"%{normalized_query}%", f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%"
            ])
            
            query += f" AND ({conditions})"

        # =========================
        # COLUMN-SPECIFIC SEARCHES
        # =========================
        else:
            name_filters = []

            if iupacName:
                variants = expand_greek_variants(iupacName)
                sub_filters = []
                for v in variants:
                    if exact:
                        sub_filters.append("lower(iupacname) = %s")
                        params.append(v)
                    else:
                        sub_filters.append("lower(iupacname) ILIKE %s")
                        params.append(f"%{v}%")
                name_filters.append("(" + " OR ".join(sub_filters) + ")")

            if altName:
                variants = expand_greek_variants(altName)
                sub_filters = []
                for v in variants:
                    if exact:
                        sub_filters.append("%s = ANY(alternativenames)")
                        params.append(v)
                    else:
                        sub_filters.append("lower(array_to_string(alternativenames, ',')) ILIKE %s")
                        params.append(f"%{v}%")
                name_filters.append("(" + " OR ".join(sub_filters) + ")")

            if name_filters:
                query += " AND (" + " OR ".join(name_filters) + ")"

            if casNumber:
                if exact:
                    query += " AND casnumber = %s"
                    params.append(casNumber)
                else:
                    query += " AND casnumber ILIKE %s"
                    params.append(f"%{casNumber}%")

            if cid:
                query += " AND cid = %s"
                params.append(cid)

            if minWeight and float(minWeight) > 0:
                query += " AND molweight >= %s"
                params.append(minWeight)

            if maxWeight and float(maxWeight) > 0:
                query += " AND molweight <= %s"
                params.append(maxWeight)


        # =========================
        # RDKit STRUCTURE SEARCH (UNCHANGED)
        # =========================
        if smiles and has_extension:
            mol = Chem.MolFromSmiles(smiles)
            if mol:
                if search_mode == "exact":
                    try:
                        inchi_str = Chem.MolToInchi(mol)
                        inchi_key = Chem.InchiToInchiKey(inchi_str)
                    except Exception:
                        inchi_key = MolToInchiKey(mol)
                    query += " AND (smiles=%s OR inchikey=%s)"
                    params.extend([smiles, inchi_key])

                elif search_mode == "substructure":
                    query += " AND structuremol @> mol_from_smiles(%s)"
                    params.append(smiles)

                elif search_mode == "similarity":
                    query += """
                    AND tanimoto_sml(
                        morgan_fp(structuremol),
                        morgan_fp(mol_from_smiles(%s))
                    ) >= %s
                    """
                    params.append(smiles)
                    params.append(similarity_threshold)

        df = pd.read_sql(query, conn, params=params)
        conn.close()

        # Fallback RDKit Search mode (Unchanged)
        if smiles and not has_extension and not df.empty:
            query_mol = Chem.MolFromSmiles(smiles)
            if not query_mol:
                return df

            smiles_col = 'smiles'
            inchikey_col = 'inchikey'

            if search_mode == "exact":
                try:
                    inchi_str = Chem.MolToInchi(query_mol)
                    query_inchi = Chem.InchiToInchiKey(inchi_str)
                except Exception:
                    query_inchi = MolToInchiKey(query_mol)

                df = df[(df[inchikey_col] == query_inchi) | (df[smiles_col] == smiles)]

            elif search_mode == "substructure":
                def is_substructure(target_smiles):
                    mol = Chem.MolFromSmiles(target_smiles) if target_smiles else None
                    return mol.HasSubstructMatch(query_mol) if mol else False

                df = df[df[smiles_col].apply(is_substructure)]

            elif search_mode == "similarity":
                query_fp = AllChem.GetMorganFingerprintAsBitVect(query_mol, 2, nBits=2048)

                def similarity(target_smiles):
                    mol = Chem.MolFromSmiles(target_smiles) if target_smiles else None
                    if not mol:
                        return 0.0
                    fp = AllChem.GetMorganFingerprintAsBitVect(mol, 2, nBits=2048)
                    return DataStructs.TanimotoSimilarity(query_fp, fp)

                df["similarity"] = df[smiles_col].apply(similarity)
                df = df[df["similarity"] >= similarity_threshold]
                df = df.sort_values(by="similarity", ascending=False)

        return df

    except Exception as e:
        print(f"Error during molecule search: {e}")
        return None