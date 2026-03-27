import os
import sys
import psycopg2
from dotenv import load_dotenv

print(f"Python version: {sys.version}")
print(f"Python executable: {sys.executable}")

def check_env():
    print("--- Environment Check ---")
    load_dotenv()
    required_vars = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        print(f"[FAIL] Missing environment variables: {', '.join(missing)}")
        return False
    print("[PASS] Environment variables loaded.")
    return True

def check_dependencies():
    print("\n--- Dependency Check ---")
    dependencies = ["rdkit", "psycopg2", "streamlit", "fastapi", "pandas"]
    all_ok = True
    for dep in dependencies:
        try:
            __import__(dep)
            print(f"[PASS] {dep} is installed.")
        except ImportError:
            print(f"[FAIL] {dep} is NOT installed.")
            all_ok = False
    return all_ok

try:
    import rdkit
    print(f"rdkit version: {rdkit.__version__}")
    print(f"rdkit path: {rdkit.__path__}")
except ImportError as e:
    print(f"FAILED to import rdkit: {e}")

submodules = [
    "rdkit.Chem",
    "rdkit.Chem.inchi",
    "rdkit.Chem.AllChem",
    "rdkit.Chem.Descriptors",
    "rdkit.Chem.rdFingerprintGenerator"
    ]

for sub in submodules:
    try:
        print(f"Attempting to import {sub}...")
        __import__(sub)
        print(f"  [SUCCESS] {sub} imported.")
    except ImportError as e:
        print(f"  [FAILED] {sub}: {e}")
    except Exception as e:
        print(f"  [ERROR] {sub}: {e}")


def check_db_connection():
    print("\n--- Database Connection Check ---")
    load_dotenv()
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            port=os.getenv("DB_PORT")
        )
        print("[PASS] Database connection successful!")
        
        cur = conn.cursor()
        cur.execute("SELECT version();")
        print(f"   PostgreSQL Version: {cur.fetchone()[0]}")
        
        # Check if RDKit extension is enabled
        try:
            cur.execute("SELECT * FROM pg_extension WHERE extname = 'rdkit';")
            if cur.fetchone():
                print("[PASS] RDKit extension is enabled.")
            else:
                print("[WARN] RDKit extension is NOT enabled in this database.")
        except Exception:
            print("[FAIL] Error checking RDKit extension.")
            
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[FAIL] Database connection failed: {e}")
        return False

def main():
    env_ok = check_env()
    deps_ok = check_dependencies()
    db_ok = check_db_connection()
    
    print("\n--- Summary ---")
    if env_ok and deps_ok and db_ok:
        print("Everything looks good! You're ready to run 'python init_db.py'.")
    else:
        print("Please fix the issues above to ensure smooth operation.")

if __name__ == "__main__":
    main()
