import os
import re
import json
import logging
from pathlib import Path
from db import get_connection
from rdkit import Chem
from rdkit.Chem.inchi import MolToInchiKey

logger = logging.getLogger(__name__)

# Absolute directory of this script — used for path validation
_SCRIPT_DIR = Path(__file__).resolve().parent


def generate_inchikey(smiles):
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None, "Invalid SMILES"
        inchikey = MolToInchiKey(mol)
        return inchikey, None
    except Exception as e:
        return None, type(e).__name__


def insert_samples(json_file="molecules_100.json"):
    # Resolve and validate path to prevent directory traversal
    resolved = (_SCRIPT_DIR / json_file).resolve()
    if not str(resolved).startswith(str(_SCRIPT_DIR)):
        logger.error("Rejected path outside project directory: %s", json_file)
        return

    if not resolved.exists():
        logger.error("JSON file not found: %s", resolved.name)
        return

    with open(resolved, "r", encoding="utf-8") as f:
        samples = json.load(f)

    conn = get_connection()
    cur = conn.cursor()

    inserted = 0
    skipped = 0
    failed = 0

    for s in samples:

        try:
            smiles = s.get("smiles")

            if not smiles:
                logger.warning("Missing SMILES for entry (CID omitted).")
                failed += 1
                continue

            mol = Chem.MolFromSmiles(smiles)

            if mol is None:
                logger.warning("Invalid SMILES encountered — skipping entry.")
                failed += 1
                continue

            inchikey, error = generate_inchikey(smiles)

            if not inchikey:
                logger.warning("Error generating InChIKey — skipping entry: %s", error)
                failed += 1
                continue

            from psycopg2 import sql as psycopg2_sql
            table_name = os.getenv("MOLECULES_TABLE", "").strip().lower()

            allowed_tables = {
                t.strip().lower()
                for t in os.getenv("ALLOWED_TABLES", "").split(",")
                if t.strip()
            }

            if not table_name:
                raise ValueError("MOLECULES_TABLE is not set")

            if not allowed_tables:
                raise ValueError("ALLOWED_TABLES is not set")

            if not re.match(r'^[a-z0-9_]+$', table_name):
                raise ValueError(f"Invalid table name format in config: {table_name}")

            if table_name not in allowed_tables:
                raise ValueError(f"Unauthorized table name: {table_name}")

            query = psycopg2_sql.SQL("""
                INSERT INTO {}
                (cid, iupacname, casnumber, alternativenames, smiles, inchikey, molweight)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (cid) DO NOTHING
            """).format(psycopg2_sql.Identifier(table_name))

            cur.execute(query, (
                s.get("cid"),
                s.get("iupacName"),
                s.get("casNumber"),
                s.get("alternativeNames", []),
                smiles,
                inchikey,
                s.get("molWeight")
            ))

            if cur.rowcount == 0:
                skipped += 1
            else:
                inserted += 1

        except Exception:
            logger.error("Error inserting molecule — skipping and rolling back.", exc_info=False)
            conn.rollback()
            failed += 1

    conn.commit()
    cur.close()
    conn.close()

    logger.info("Insertion complete. Inserted: %d | Skipped: %d | Failed: %d", inserted, skipped, failed)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    insert_samples()