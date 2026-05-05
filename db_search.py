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

_LIKE_ESCAPE_CHAR  = "!"


_SELECTED_COLUMNS = [
    "id",
    "casNumber",
    "alternativeNames",
    "cid",
    "iupacName",
    "molWeight",
    "inchiKey",
    "createdAt",
    "updatedAt",
    "mol_id",
]
 
_SELECT_TEMPLATE = "SELECT {cols} FROM {tbl} WHERE 1=1"


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


def check_rdkit_extension(conn) -> bool:
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_extension WHERE extname='rdkit';")
        exists = cur.fetchone() is not None
        cur.close()
        return exists
    except Exception:
        return False


from psycopg2 import sql as S


def search_molecules(
    smiles: str = None,       # SMILES string submitted by the caller
    iupacName=None,
    casNumber=None,
    altName=None,
    cid=None,
    minWeight=None,
    maxWeight=None,
    search_mode="",
    similarity_threshold=0.7,
    limit="",
    offset=0,
):
    conn = None
    try:
        conn = get_connection()
        has_rdkit = check_rdkit_extension(conn)

        table_name = os.getenv("MOLECULES_TABLE", "")
        if not table_name:
            raise ValueError("MOLECULES_TABLE is not set")
        if not re.match(r'^[A-Za-z0-9_]+$', table_name):
            raise ValueError(f"Invalid table name: {table_name}")

        # ── Canonical SELECT: every DB→API alias is defined here ───────────────
        query = S.SQL(_SELECT_TEMPLATE).format(
            tbl=S.Identifier(table_name),
        )
        params = []
        name_filters = []

        # ── iupacName ──────────────────────────────────────────────────────────
        if iupacName:
            norm    = normalize_for_search(iupacName)
            escaped = escape_like(norm)
            name_filters.append(S.SQL(
                "(lower(replace(replace({col}, '-', ' '), '_', ' ')) = %s "
                "OR lower(replace(replace({col}, '-', ' '), '_', ' ')) LIKE %s ESCAPE '!')"
            ).format(col=S.Identifier("iupacName")))
            params.extend([norm, f"%{escaped}%"])

        # ── alternativeNames ───────────────────────────────────────────────────
        if altName:
            norm    = normalize_for_search(altName, preserve_hyphens=True)
            escaped = escape_like(norm)
            greek_norm = S.SQL(
                "lower(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace("
                "x, 'α','alpha'),'Α','alpha'),'β','beta'),'Β','beta'),'γ','gamma'),'Γ','gamma')"
                ",'δ','delta'),'Δ','delta'),'ε','epsilon'),'Ε','epsilon'))"
            )
            exact_match   = S.SQL("%s IN (SELECT {} FROM unnest({}) x)").format(
                greek_norm, S.Identifier("alternativeNames"))
            partial_match = S.SQL(
                "EXISTS (SELECT 1 FROM unnest({}) x WHERE {} LIKE %s ESCAPE '!')"
            ).format(S.Identifier("alternativeNames"), greek_norm)
            name_filters.append(S.SQL("({} OR {})").format(exact_match, partial_match))
            params.extend([norm, f"%{escaped}%"])

        # ── casNumber ──────────────────────────────────────────────────────────
        if casNumber:
            name_filters.append(S.SQL("{} ILIKE %s").format(S.Identifier("casNumber")))
            params.append(f"%{casNumber}%")

        if name_filters:
            query += S.SQL(" AND ({})").format(S.SQL(" OR ").join(name_filters))

        # ── cid ────────────────────────────────────────────────────────────────
        if cid is not None:
            query += S.SQL(" AND CAST({} AS TEXT) LIKE %s ESCAPE '!'").format(
                S.Identifier("cid"))
            params.append(f"%{cid}%")

        # ── molWeight ──────────────────────────────────────────────────────────
        if minWeight and float(minWeight) > 0:
            query += S.SQL(" AND {} >= %s").format(S.Identifier("molWeight"))
            params.append(minWeight)
        if maxWeight and float(maxWeight) > 0:
            query += S.SQL(" AND {} <= %s").format(S.Identifier("molWeight"))
            params.append(maxWeight)

        # ── structural search (RDKit extension path) ───────────────────────────
        # smiles is the caller-supplied SMILES string.
        # mol_from_smiles() / morgan_fp() are RDKit SQL functions that operate
        # on the "structureMol" DB column (mol type).
        if smiles and has_rdkit:
            mol = Chem.MolFromSmiles(smiles)          # Python-side validation only
            if mol:
                if search_mode == "exact":
                    try:
                        inchi_key = Chem.InchiToInchiKey(Chem.MolToInchi(mol))
                    except Exception:
                        inchi_key = MolToInchiKey(mol)
                    # Match via inchikey (text alias, available in WHERE subquery)
                    query += S.SQL(" AND {} = %s").format(S.Identifier("inchiKey"))
                    params.append(inchi_key)

                elif search_mode == "substructure":
                    query += S.SQL(
                        " AND {} @> mol_from_smiles(%s)"
                    ).format(S.Identifier("structureMol"))
                    params.append(smiles)

                elif search_mode == "similarity":
                    query += S.SQL(
                        " AND tanimoto_sml(morgan_fp({}), morgan_fp(mol_from_smiles(%s))) >= %s"
                    ).format(S.Identifier("structureMol"))
                    params.extend([smiles, similarity_threshold])

        # ── LIMIT / OFFSET ─────────────────────────────────────────────────────
        needs_python_filter = bool(smiles and not has_rdkit)

        if needs_python_filter:
            pass
        else:
            query += S.SQL(" LIMIT %s OFFSET %s")
            params.extend([limit, offset])

        df = pd.read_sql(query.as_string(conn), conn, params=params)
        conn.close()

        if needs_python_filter and not df.empty:
            query_mol = Chem.MolFromSmiles(smiles)
            if not query_mol:
                return df.iloc[offset: offset + limit]

            smiles_col   = "smiles"    # SQL alias for mol_to_smiles(structureMol)
            inchikey_col = "inchikey"  # SQL alias for inchiKey

            if search_mode == "exact":
                try:
                    query_inchi = Chem.InchiToInchiKey(Chem.MolToInchi(query_mol))
                except Exception:
                    query_inchi = MolToInchiKey(query_mol)
                df = df[
                    (df[inchikey_col] == query_inchi) |
                    (df[smiles_col] == smiles)
                ]

            elif search_mode == "substructure":
                def is_sub(s):
                    m = Chem.MolFromSmiles(s) if s else None
                    return m.HasSubstructMatch(query_mol) if m else False
                df = df[df[smiles_col].apply(is_sub)]

            elif search_mode == "similarity":
                qfp = AllChem.GetMorganFingerprintAsBitVect(query_mol, 2, nBits=2048)
                def sim(s):
                    m = Chem.MolFromSmiles(s) if s else None
                    if not m:
                        return 0.0
                    return DataStructs.TanimotoSimilarity(
                        qfp, AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048))
                df["similarity"] = df[smiles_col].apply(sim)
                df = df[df["similarity"] >= similarity_threshold].sort_values(
                    "similarity", ascending=False)

            df = df.iloc[offset: offset + limit]

        return df

    except Exception as e:
        logger.error("Error during molecule search: %s — %s",
            type(e).__name__, e, exc_info=True,
        )
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass