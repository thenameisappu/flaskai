import os
import re
import logging
from db import get_connection

logger = logging.getLogger(__name__)

def init_db():
    logger.info("Initializing database...")
    try:
        conn = get_connection()
        cur = conn.cursor()

        logger.info("Checking for RDKit extension...")
        try:
            cur.execute("CREATE EXTENSION IF NOT EXISTS rdkit;")
            conn.commit()
            logger.info("[PASS] RDKit enabled.")
            has_rdkit = True
        except Exception as e:
            conn.rollback()
            logger.warning(f"[WARN] RDKit not available: {e}")
            logger.warning("Running in 'Python Fallback' mode - advanced SQL structure search will be disabled.")
            has_rdkit = False

        logger.info("Setting up tables...")

        # Base columns - defined as a constant; no user input involved.
        base_columns = (
            "id SERIAL PRIMARY KEY, "
            "cid INTEGER UNIQUE, "
            "iupacName TEXT, "
            "casNumber TEXT, "
            "alternativeNames TEXT[], "
            "smiles TEXT, "
            "inchiKey TEXT, "
            "molWeight FLOAT"
        )

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

        if has_rdkit:
            query = psycopg2_sql.SQL("CREATE TABLE IF NOT EXISTS {} ({}, structureMol mol);").format(
                psycopg2_sql.Identifier(table_name),
                psycopg2_sql.SQL(base_columns)
            )
            cur.execute(query)
        else:
            query = psycopg2_sql.SQL("CREATE TABLE IF NOT EXISTS {} ({});").format(
                psycopg2_sql.Identifier(table_name),
                psycopg2_sql.SQL(base_columns)
            )
            cur.execute(query)

        logger.info("Setting up indexes...")
        if has_rdkit:
            cur.execute(
                psycopg2_sql.SQL("CREATE INDEX IF NOT EXISTS mol_structure_idx ON {} USING gist(structureMol);").format(psycopg2_sql.Identifier(table_name))
            )

        cur.execute(psycopg2_sql.SQL("CREATE INDEX IF NOT EXISTS mol_inchi_idx ON {}(inchiKey);").format(psycopg2_sql.Identifier(table_name)))
        cur.execute(psycopg2_sql.SQL("CREATE INDEX IF NOT EXISTS mol_name_idx ON {}(iupacName);").format(psycopg2_sql.Identifier(table_name)))

        conn.commit()
        logger.info("[OK] Database initialized successfully.")
        cur.close()
        conn.close()
    except Exception:
        logger.error("[ERROR] Failed to initialize database.", exc_info=False)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    
