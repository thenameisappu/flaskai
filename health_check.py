import os
import sys
import glob
import ast
import shutil
import logging
import argparse
import psycopg2
import urllib.request
import urllib.error
import socket
from dotenv import load_dotenv

# Configure logging for readable output
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def check_env():
    """Environment Validation: Checks if .env exists and has required keys."""
    logger.info("--- 1. Environment Validation ---")
    if not os.path.exists(".env"):
        logger.warning("[WARN] .env file is missing. The system might rely on default or system exports.")
    
    load_dotenv()
    required_vars = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        logger.warning("[FAIL] Missing environment variables: %s", ', '.join(missing))
        return False
    logger.info("[PASS] All required database environment variables are loaded.")
    return True


def check_dependencies():
    """Deployment Readiness: Checks if Python dependencies are installed."""
    logger.info("\n--- 2. Python Dependency Check ---")
    dependencies = ["rdkit", "psycopg2", "fastapi", "pandas", "uvicorn"]
    all_ok = True
    for dep in dependencies:
        try:
            __import__(dep)
            logger.info("[PASS] %s is installed.", dep)
        except ImportError:
            logger.warning("[FAIL] %s is NOT installed.", dep)
            all_ok = False
    return all_ok


def check_db_connection():
    """Database Functionality: Verifies PostgreSQL connection and RDKit extension."""
    logger.info("\n--- 3. Database Integrity Check ---")
    load_dotenv()
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            database=os.getenv("DB_NAME", "postgres"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            port=os.getenv("DB_PORT", "5433")
        )
        logger.info("[PASS] Database connection successful!")

        cur = conn.cursor()
        cur.execute("SELECT version();")
        version_str = str(cur.fetchone()[0])[:60]
        logger.info("       => PostgreSQL Version: %s", version_str)

        try:
            cur.execute("SELECT * FROM pg_extension WHERE extname = 'rdkit';")
            if cur.fetchone():
                logger.info("       => [PASS] RDKit extension is enabled in the database.")
            else:
                logger.warning("       => [WARN] RDKit extension is NOT enabled in this database.")
        except Exception as e:
            logger.warning(f"       => [WARN] Error checking RDKit extension: {e}")

        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error("[FAIL] Database connection failed. Verify DB_* variables and DB status.")
        return False


def check_docker_compatibility():
    """Docker Compatibility: Validates architecture platforms and execution points."""
    logger.info("\n--- 4. Docker & Deployment Compatibility Check ---")
    
    # 1. Dockerfile check
    if os.path.exists("Dockerfile"):
        with open("Dockerfile", "r", encoding="utf-8") as f:
            content = f.read()
            if "--platform=linux/amd64" in content or "--platform=linux/arm64" in content:
                logger.info("[PASS] Dockerfile architecture explicitly set (Prevents 'exec format error').")
            else:
                logger.warning("[WARN] Dockerfile architecture NOT specified. May cause 'exec format error' on M1/M2/ARM hosts deploying to Coolify/Linux VMs.")
            
            if "uvicorn api:app" in content:
                logger.info("[PASS] API entry point (uvicorn api:app) found in Dockerfile.")
            else:
                logger.warning("[WARN] uvicorn api:app not found in Dockerfile CMD. Ensure correct startup command.")
    else:
        logger.warning("[FAIL] Dockerfile is missing!")

    # 2. docker-compose check
    if os.path.exists("docker-compose.yml"):
        logger.info("[PASS] docker-compose.yml found.")
        with open("docker-compose.yml", "r", encoding="utf-8") as f:
            if "depends_on" in f.read():
                logger.info("[PASS] 'depends_on' relation exists in docker-compose.yml.")
            else:
                logger.warning("[WARN] No 'depends_on' in docker-compose.yml, API might boot before DB.")
    else:
        logger.warning("[FAIL] docker-compose.yml is missing!")


def check_file_usage():
    """File Usage Analyzer: Scans for unused Python files safely."""
    logger.info("\n--- 5. File Usage Analyzer ---")
    
    # Known project entry points that won't be imported but are required
    entry_points = {"api.py", "health_check.py", "init_db.py", "seed_data.py"}
    
    all_py_files = set(glob.glob("*.py"))
    
    imported_modules = set()
    for py_file in all_py_files:
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imported_modules.add(alias.name.split('.')[0])
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imported_modules.add(node.module.split('.')[0])
        except Exception:
            pass # Skip unparseable files

    for py_file in sorted(list(all_py_files)):
        module_name = py_file[:-3]
        if py_file in entry_points:
            logger.info(f"[REQUIRED/ENTRY] {py_file} (Core Script)")
        elif module_name in imported_modules:
            logger.info(f"[REQUIRED/MODULE] {py_file} (Imported File)")
        else:
            logger.warning(f"[UNUSED/OPTIONAL] {py_file} (Not imported by other local files)")


def cleanup(auto_clean=False):
    """Safe Cleanup: Identifies and optionally removes caches and redundant files."""
    logger.info("\n--- 6. Safe Cleanup Suggestions ---")
    to_remove = []
    
    # Traverse project avoiding .git and venv for safe scanning
    for root, dirs, files in os.walk("."):
        parts = root.split(os.sep)
        if ".git" in parts or "venv" in parts or "env" in parts:
            continue
            
        # Target caches
        if "__pycache__" in dirs:
            to_remove.append(os.path.join(root, "__pycache__"))
        
        # Target pyc files
        for f in files:
            if f.endswith(".pyc"):
                to_remove.append(os.path.join(root, f))

    if os.path.exists("venv") or os.path.exists("env"):
        logger.info("[SUGGESTION] Python virtual environment ('venv/' or 'env/') found. This is optional for Docker deployments but required locally.")

    if not to_remove:
        logger.info("[PASS] No cleanup needed. Project is clean.")
        return

    for item in to_remove:
        if auto_clean:
            try:
                if os.path.isdir(item):
                    shutil.rmtree(item)
                else:
                    os.remove(item)
                logger.info(f"   [DELETED] {item}")
            except Exception as e:
                logger.error(f"   [FAIL] Could not delete {item}: {e}")
        else:
            logger.info(f"   [SUGGESTION] Safely Removable Cache/Bytecode: {item}")
            
    if not auto_clean and to_remove:
        logger.info("\n(Tip: Run 'python health_check.py --clean' to auto-remove these cache files)")


def check_coolify_health():
    """Coolify Health Check: Validates /health endpoint and docker-compose healthcheck config."""
    logger.info("\n--- 7. Coolify Health Check Validation ---")

    load_dotenv()
    all_ok = True

    # ── 7a. Check /health route exists in api.py ───────────────────────────────
    if os.path.exists("api.py"):
        with open("api.py", "r", encoding="utf-8") as f:
            api_content = f.read()
        if '@app.get("/health")' in api_content or "@app.get('/health')" in api_content:
            logger.info("[PASS] /health endpoint is defined in api.py.")
        else:
            logger.warning("[FAIL] /health endpoint is NOT defined in api.py.")
            logger.warning('       => Add to api.py:  @app.get("/health")')
            logger.warning('                           async def health(): return {"status": "ok"}')
            all_ok = False
    else:
        logger.warning("[WARN] api.py not found — cannot verify /health route.")
        all_ok = False

    # ── 7b. Check docker-compose healthcheck block for the api service ─────────
    compose_file = None
    for name in ("docker-compose.yml", "docker-compose.yaml"):
        if os.path.exists(name):
            compose_file = name
            break

    if compose_file:
        with open(compose_file, "r", encoding="utf-8") as f:
            compose_content = f.read()

        if "healthcheck" in compose_content:
            if "/health" in compose_content:
                logger.info("[PASS] docker-compose healthcheck block references /health endpoint.")
            else:
                logger.warning("[WARN] docker-compose healthcheck found but does not reference /health.")
                all_ok = False
        else:
            logger.warning("[FAIL] No 'healthcheck' block found in %s.", compose_file)
            logger.warning("       => Coolify will show 'No health check configured' warning.")
            logger.warning("       => Add this under your api service in %s:", compose_file)
            logger.warning("          healthcheck:")
            logger.warning('            test: ["CMD-SHELL", "curl -sf http://localhost:8000/health || exit 1"]')
            logger.warning("            interval: 15s")
            logger.warning("            timeout: 5s")
            logger.warning("            start_period: 20s")
            logger.warning("            retries: 3")
            all_ok = False
    else:
        logger.warning("[WARN] No docker-compose.yml / docker-compose.yaml found.")
        all_ok = False

    # ── 7c. Live reachability check of /health endpoint ────────────────────────
    api_port = os.getenv("API_PORT", "8000")
    health_url = f"http://localhost:{api_port}/health"
    logger.info("       Attempting live check: %s", health_url)

    try:
        with urllib.request.urlopen(health_url, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            if resp.status == 200 and "ok" in body:
                logger.info("[PASS] /health is live and returned 200 OK. (%s)", body.strip())
            else:
                logger.warning("[WARN] /health responded with status %s: %s", resp.status, body.strip())
                all_ok = False
    except urllib.error.URLError as e:
        logger.warning("[SKIP] Could not reach %s — API may not be running locally. (%s)", health_url, e.reason)
    except socket.timeout:
        logger.warning("[SKIP] Connection to %s timed out.", health_url)

    # ── 7d. Coolify UI reminder ────────────────────────────────────────────────
    logger.info("       Coolify UI → Resource → Settings → Health Check:")
    logger.info("          Path : /health")
    logger.info("          Port : %s", api_port)

    if all_ok:
        logger.info("[PASS] Coolify health check configuration looks correct.")
    else:
        logger.warning("[WARN] One or more Coolify health check issues found. See above.")

    return all_ok


def main():
    parser = argparse.ArgumentParser(description="Full Project Health Analyzer & Cleanup")
    parser.add_argument("--clean", action="store_true", help="Auto-delete safe files like __pycache__ and *.pyc")
    args = parser.parse_args()

    logger.info("==================================================")
    logger.info("        FLASK-AI HEALTH & DEPLOYMENT CHECK        ")
    logger.info("==================================================")

    check_env()
    check_dependencies()
    check_db_connection()
    check_docker_compatibility()
    check_file_usage()
    cleanup(auto_clean=args.clean)
    check_coolify_health()

    logger.info("\n==================================================")
    logger.info("                 CHECK COMPLETE                   ")
    logger.info("==================================================")


if __name__ == "__main__":
    main()
