import os
from db import get_connection

def init_db():
    print("Initializing database...")
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # 1. Try to enable RDKit extension (might fail on native Windows)
        print("Checking for RDKit extension...")
        try:
            cur.execute("CREATE EXTENSION IF NOT EXISTS rdkit;")
            conn.commit()
            print("[OK] RDKit extension enabled.")
            has_rdkit = True
        except Exception as e:
            conn.rollback()
            print(f"[WARN] RDKit extension not available: {e}")
            print("Running in 'Python Fallback' mode - advanced SQL structure search will be disabled.")
            has_rdkit = False

        # 2. Create molecules table
        print("Setting up tables...")
        
        # Base columns
        columns = """
            id SERIAL PRIMARY KEY,
            cid INTEGER UNIQUE,
            iupacName TEXT,
            casNumber TEXT,
            alternativeNames TEXT[],
            smiles TEXT,
            inchiKey TEXT,
            molWeight FLOAT
        """
        
        if has_rdkit:
            # Add specialized RDKit column
            columns += ", structureMol mol"
            
        create_table_sql = f"CREATE TABLE IF NOT EXISTS molecules ({columns});"
        cur.execute(create_table_sql)
        
        # 3. Create indexes (only if RDKit is available for gist)
        print("Setting up indexes...")
        if has_rdkit:
            cur.execute("CREATE INDEX IF NOT EXISTS mol_structure_idx ON molecules USING gist(structureMol);")
        
        cur.execute("CREATE INDEX IF NOT EXISTS mol_inchi_idx ON molecules(inchiKey);")
        cur.execute("CREATE INDEX IF NOT EXISTS mol_name_idx ON molecules(iupacName);")
        
        conn.commit()
        print("[OK] Database initialized successfully.")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[ERROR] Failed to initialize database: {e}")

if __name__ == "__main__":
    init_db()
