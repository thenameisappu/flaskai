import os
import re
import logging
import pandas as pd
from db import get_connection
from rdkit import Chem
from rdkit.Chem.inchi import MolToInchiKey
from rdkit.Chem import AllChem, DataStructs
import warnings

from normalization import GREEK_SYMBOLS

warnings.filterwarnings('ignore', category=UserWarning, module='pandas')

logger = logging.getLogger(__name__)

_DB_ROW_HARD_LIMIT = 1000

_LIKE_ESCAPE_CHAR = "!"

def escape_like(value: str) -> str:
    return (
        value
        .replace(_LIKE_ESCAPE_CHAR, _LIKE_ESCAPE_CHAR * 2)
        .replace("%",               _LIKE_ESCAPE_CHAR + "%")
        .replace("_",               _LIKE_ESCAPE_CHAR + "_")
    )

def normalize_for_search(text: str, preserve_hyphens: bool = False) -> str:
    if not text:
        return ""
    result = text.lower()
    for symbol, word in GREEK_SYMBOLS.items():
        result = result.replace(symbol, word)
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


from psycopg2 import sql as psycopg2_sql

def search_molecules(
    smiles=None,
    iupacName=None,
    casNumber=None,
    altName=None,
    cid=None,
    minWeight=None,
    maxWeight=None,
    search_mode="",
    similarity_threshold=0.7,
    limit=200,
    offset=0,
):
    try:
        conn = get_connection()
        has_extension = check_rdkit_extension(conn)

        table_name = os.getenv("MOLECULES_TABLE", "")

        if not table_name:
            raise ValueError("MOLECULES_TABLE is not set")

        if not re.match(r'^[A-Za-z0-9_]+$', table_name):
            raise ValueError(f"Invalid table name format in config: {table_name}")

        query = psycopg2_sql.SQL("SELECT * FROM {} WHERE 1=1").format(
            psycopg2_sql.Identifier(table_name)
        )
        params = []
        name_filters = []

        ALLOWED_COLUMNS = {"cid", "casnumber", "molweight", "smiles", "inchikey", "iupacname", "alternativenames"}
        search_cols = []
        if iupacName: search_cols.append("iupacname")
        if altName: search_cols.append("alternativenames")
        if casNumber: search_cols.append("casnumber")
        if cid is not None: search_cols.append("cid")
        if minWeight or maxWeight: search_cols.append("molweight")
        if smiles and has_extension: search_cols.extend(["smiles", "inchikey"])

        for col in search_cols:
            if col not in ALLOWED_COLUMNS:
                raise ValueError("Invalid column name")

        # ── IUPAC Name ─────────────────────────────────────────────────────────
        if iupacName:
            iupac_norm = normalize_for_search(iupacName)
            iupac_escaped = escape_like(iupac_norm)
            name_filters.append(psycopg2_sql.SQL(
                "(lower(replace(replace(\"iupacName\", '-', ' '), '_', ' ')) = %s "
                "OR lower(replace(replace(\"iupacName\", '-', ' '), '_', ' ')) LIKE %s ESCAPE '!')"
            ))
            params.extend([iupac_norm, f"%{iupac_escaped}%"])

        # ── Alternative Names ──────────────────────────────────────────────────
        if altName:
            alt_norm = normalize_for_search(altName, preserve_hyphens=True)
            alt_escaped = escape_like(alt_norm)
            _db_greek_norm = psycopg2_sql.SQL(
                "lower(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace("
                "x, 'α','alpha'),'Α','alpha'),'β','beta'),'Β','beta'),'γ','gamma'),'Γ','gamma')"
                ",'δ','delta'),'Δ','delta'),'ε','epsilon'),'Ε','epsilon'))"
            )
            exact_match  = psycopg2_sql.SQL("%s IN (SELECT {} FROM unnest(\"alternativeNames\") x)").format(_db_greek_norm)
            partial_match = psycopg2_sql.SQL(
                "EXISTS (SELECT 1 FROM unnest(\"alternativeNames\") x WHERE {} LIKE %s ESCAPE '!')"
            ).format(_db_greek_norm)
            
            name_filters.append(psycopg2_sql.SQL("({} OR {})").format(exact_match, partial_match))
            params.extend([alt_norm, f"%{alt_escaped}%"])

        # ── CAS Number — exact match ───────────────────────────────────────────
        if casNumber:
            name_filters.append(psycopg2_sql.SQL("\"casNumber\" ILIKE %s"))
            params.append(f"%{casNumber}%")

        if name_filters:
            query += psycopg2_sql.SQL(" AND ({})").format(psycopg2_sql.SQL(" OR ").join(name_filters))

        # ── CID — cast to TEXT for partial numeric search ───────────────────────
        if cid is not None:
            query += psycopg2_sql.SQL(" AND CAST(\"cid\" AS TEXT) LIKE %s ESCAPE '!'")
            params.append(f"%{cid}%")

        # ── Molecular weight range ─────────────────────────────────────────────
        if minWeight and float(minWeight) > 0:
            query += psycopg2_sql.SQL(" AND \"molWeight\" >= %s")
            params.append(minWeight)

        if maxWeight and float(maxWeight) > 0:
            query += psycopg2_sql.SQL(" AND \"molWeight\" <= %s")
            params.append(maxWeight)

        # ── RDKit structural filters (extension path) ──────────────────────────
        if smiles and has_extension:
            mol = Chem.MolFromSmiles(smiles)
            if mol:
                if search_mode == "exact":
                    try:
                        inchi_str = Chem.MolToInchi(mol)
                        inchi_key = Chem.InchiToInchiKey(inchi_str)
                    except Exception:
                        inchi_key = MolToInchiKey(mol)
                    query += psycopg2_sql.SQL(" AND (\"structureMol\" = %s OR \"inchiKey\" = %s)")
                    params.extend([smiles, inchi_key])

                elif search_mode == "substructure":
                    query += psycopg2_sql.SQL(" AND \"structureMol\"::mol @> mol_from_smiles(%s)")
                    params.append(smiles)

                elif search_mode == "similarity":
                    query += psycopg2_sql.SQL(
                        " AND tanimoto_sml(morgan_fp(\"structureMol\"::mol), morgan_fp(mol_from_smiles(%s))) >= %s"
                    )
                    params.extend([smiles, similarity_threshold])

        # ── LIMIT / OFFSET ─────────────────────────────────────────────────────
        needs_python_filter = bool(smiles and not has_extension)

        if needs_python_filter:
            query += psycopg2_sql.SQL(" LIMIT %s")
            params.append(_DB_ROW_HARD_LIMIT)
        else:
            query += psycopg2_sql.SQL(" LIMIT %s OFFSET %s")
            params.extend([limit, offset])

        df = pd.read_sql(query.as_string(conn), conn, params=params)
        conn.close()

        # ── Python-fallback structural filtering ───────────────────────────────
        if needs_python_filter and not df.empty:
            query_mol = Chem.MolFromSmiles(smiles)
            if not query_mol:
                return df.iloc[offset: offset + limit]

            # DB column is "structureMol" (mol type); "inchiKey" is the text identifier
            smiles_col   = 'structureMol'
            inchikey_col = 'inchiKey'

            if search_mode == "exact":
                try:
                    inchi_str   = Chem.MolToInchi(query_mol)
                    query_inchi = Chem.InchiToInchiKey(inchi_str)
                except Exception:
                    query_inchi = MolToInchiKey(query_mol)
                df = df[
                    (df[inchikey_col] == query_inchi) | (df[smiles_col] == smiles)
                ]

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

            # Apply user-requested page slice AFTER Python filtering.
            df = df.iloc[offset: offset + limit]

        return df

    except Exception as e:
        logger.error(
            "Error during molecule search: %s — %s",
            type(e).__name__,
            e,
            exc_info=True,
        )
        return None
        