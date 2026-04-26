import os
import re
import json
import logging
from pathlib import Path
from db import get_connection
from rdkit import Chem
from rdkit.Chem.inchi import MolToInchiKey

logger = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).resolve().parent


def generate_inchikey(smiles):
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None, "Invalid SMILES"
        return MolToInchiKey(mol), None
    except Exception as e:
        return None, type(e).__name__


def insert_samples(json_file="molecules_100.json"):
    resolved = (_SCRIPT_DIR / json_file).resolve()

    if not str(resolved).startswith(str(_SCRIPT_DIR)):
        logger.error("Rejected path outside project directory: %s", json_file)
        return

    if not resolved.exists():
        logger.error("JSON file not found: %s", resolved.name)
        return

    with open(resolved, "r", encoding="utf-8") as f:
        samples = json.load(f)

    conn = None
    cur = None

    try:
        conn = get_connection()
        cur = conn.cursor()

        inserted = 0
        failed = 0

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
            raise ValueError(f"Invalid table name format: {table_name}")

        if table_name not in allowed_tables:
            raise ValueError(f"Unauthorized table name: {table_name}")

        query = psycopg2_sql.SQL("""
            INSERT INTO {}
            (cid, iupacname, casnumber, alternativenames, smiles, inchikey, molweight)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (cid) DO NOTHING
        """).format(psycopg2_sql.Identifier(table_name))

        batch_size = 50
        batch = []

        for s in samples:
            try:
                smiles = s.get("smiles")

                if not smiles:
                    logger.warning("Missing SMILES — skipping entry")
                    failed += 1
                    continue

                mol = Chem.MolFromSmiles(smiles)
                if mol is None:
                    logger.warning("Invalid SMILES — skipping")
                    failed += 1
                    continue

                inchikey, error = generate_inchikey(smiles)
                if not inchikey:
                    logger.warning("InChIKey error: %s", error)
                    failed += 1
                    continue

                batch.append((
                    s.get("cid"),
                    s.get("iupacName"),
                    s.get("casNumber"),
                    s.get("alternativeNames", []),
                    smiles,
                    inchikey,
                    s.get("molWeight")
                ))

                # Insert batch
                if len(batch) >= batch_size:
                    cur.executemany(query.as_string(conn), batch)
                    conn.commit()
                    inserted += cur.rowcount
                    batch.clear()

            except Exception:
                logger.error("Error processing molecule", exc_info=False)
                conn.rollback()
                failed += 1

        # Insert remaining
        if batch:
            cur.executemany(query.as_string(conn), batch)
            conn.commit()
            inserted += cur.rowcount

        logger.info(
            "Insertion complete | Inserted: %d | Failed: %d",
            inserted, failed
        )

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    insert_samples()