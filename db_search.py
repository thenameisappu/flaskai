import pandas as pd
from db import get_connection
from rdkit import Chem
from rdkit.Chem.inchi import MolToInchiKey
from rdkit.Chem import AllChem, DataStructs
import warnings

warnings.filterwarnings('ignore', category=UserWarning, module='pandas')

# Full Greek symbol → ascii word map (covers all common chemical name usage)
_GREEK_TO_ASCII = {
    'α': 'alpha', 'Α': 'alpha',
    'β': 'beta',  'Β': 'beta',
    'γ': 'gamma', 'Γ': 'gamma',
    'δ': 'delta', 'Δ': 'delta',
    'ε': 'epsilon', 'Ε': 'epsilon',
    'ζ': 'zeta',  'Ζ': 'zeta',
    'η': 'eta',   'Η': 'eta',
    'θ': 'theta', 'Θ': 'theta',
    'μ': 'mu',    'Μ': 'mu',
    'ω': 'omega', 'Ω': 'omega',
}


def normalize_for_search(text: str, preserve_hyphens: bool = False) -> str:
    """Normalize a chemical name for exact matching:
    - Lowercase
    - Replace Greek symbols with ascii words
    - Replace hyphens/underscores with spaces (unless preserve_hyphens=True)
    """
    if not text:
        return ""
    result = text.lower()
    for symbol, word in _GREEK_TO_ASCII.items():
        result = result.replace(symbol.lower(), word)
    if not preserve_hyphens:
        result = result.replace('-', ' ').replace('_', ' ')
    return result


def check_rdkit_extension(conn):
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_extension WHERE extname='rdkit';")
        exists = cur.fetchone() is not None
        cur.close()
        return exists
    except Exception:
        return False

def search_molecules(
    smiles=None,
    iupacName=None,
    casNumber=None,
    altName=None,
    cid=None,
    minWeight=None,
    maxWeight=None,

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
        # COLUMN-SPECIFIC SEARCHES
        # =========================
        name_filters = []

        if iupacName:
            # Normalize input: lowercase, Greek symbols → ascii, hyphens/underscores → spaces
            iupac_norm = normalize_for_search(iupacName)
            sub_filters = []
            # DB side: apply same normalization inline in SQL
            sub_filters.append(
                "lower(replace(replace(iupacname, '-', ' '), '_', ' ')) = %s"
            )
            params.append(iupac_norm)
            name_filters.append("(" + " OR ".join(sub_filters) + ")")

        if altName:
            # Normalize input: lowercase, Greek symbols → ascii, preserve hyphens
            alt_norm = normalize_for_search(altName, preserve_hyphens=True)

            _db_greek_norm = (
                "lower("
                "replace(replace(replace(replace(replace(replace(replace(replace(replace(replace("
                "x, 'α','alpha'),'Α','alpha'),'β','beta'),'Β','beta'),'γ','gamma'),'Γ','gamma')"
                ",'δ','delta'),'Δ','delta'),'ε','epsilon'),'Ε','epsilon'))"
            )

            # Exact match: normalized input = normalized DB element (via UNNEST)
            exact_match = (
                f"%s IN (SELECT {_db_greek_norm} FROM unnest(alternativenames) x)"
            )

            # Partial match: normalized DB element ILIKE %input% (via EXISTS + UNNEST)
            partial_match = (
                f"EXISTS (SELECT 1 FROM unnest(alternativenames) x WHERE {_db_greek_norm} ILIKE %s)"
            )

            sub_filters = [exact_match, partial_match]
            # Exact match param first, then partial with wildcards
            params.append(alt_norm)
            params.append(f"%{alt_norm}%")

            name_filters.append("(" + " OR ".join(sub_filters) + ")")

        if name_filters:
            query += " AND (" + " OR ".join(name_filters) + ")"

        if casNumber:
            # Always use exact match for CAS numbers
            query += " AND casnumber = %s"
            params.append(casNumber)

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