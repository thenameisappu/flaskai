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


def check_env_json() -> dict:
    """Returns environment check as a dict (used by /health endpoint)."""
    load_dotenv()
    required_vars = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing = [v for v in required_vars if not os.getenv(v)]
    return {
        "status": "pass" if not missing else "fail",
        "env_file_exists": os.path.exists(".env"),
        "missing_vars": missing,
    }


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


def check_dependencies_json() -> dict:
    """Returns dependency check as a dict (used by /health endpoint)."""
    dependencies = ["rdkit", "psycopg2", "fastapi", "pandas", "uvicorn"]
    results = {}
    for dep in dependencies:
        try:
            __import__(dep)
            results[dep] = "installed"
        except ImportError:
            results[dep] = "missing"
    status = "pass" if all(v == "installed" for v in results.values()) else "fail"
    return {"status": status, "packages": results}


def check_db_connection():
    """Database Functionality: Verifies PostgreSQL connection and RDKit extension."""
    logger.info("\n--- 3. Database Integrity Check ---")
    load_dotenv()
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "postgresql-database-igcwckskcokscwcgswws880w"),
            database=os.getenv("DB_NAME", "flaskai"),
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


def check_db_connection_json() -> dict:
    """Returns database check as a dict (used by /health endpoint)."""
    load_dotenv()

    # Step 1: Connect
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "postgresql-database-igcwckskcokscwcgswws880w"),
            database=os.getenv("DB_NAME", "flaskai"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            port=os.getenv("DB_PORT", "5433"),
        )
    except Exception as e:
        return {
            "status": "fail",
            "failed_step": "connection",
            "error": f"Could not connect to database: {type(e).__name__}: {e}",
        }

    # Step 2: Fetch PostgreSQL version
    try:
        cur = conn.cursor()
        cur.execute("SELECT version();")
        pg_version = str(cur.fetchone()[0])[:60]
    except Exception as e:
        conn.close()
        return {
            "status": "fail",
            "failed_step": "postgres_version_query",
            "error": f"Connected but failed to query version: {type(e).__name__}: {e}",
        }

    # Step 3: Check RDKit extension
    try:
        cur.execute("SELECT 1 FROM pg_extension WHERE extname='rdkit';")
        rdkit_enabled = cur.fetchone() is not None
    except Exception as e:
        cur.close()
        conn.close()
        return {
            "status": "fail",
            "failed_step": "rdkit_extension_check",
            "error": f"Connected but failed to check RDKit extension: {type(e).__name__}: {e}",
        }

    cur.close()
    conn.close()

    return {
        "status": "pass",
        "failed_step": None,
        "postgres_version": pg_version,
        "rdkit_extension": "enabled" if rdkit_enabled else "not enabled",
    }


def check_docker_compatibility():
    """Docker Compatibility: Validates architecture platforms and execution points."""
    logger.info("\n--- 4. Docker & Deployment Compatibility Check ---")

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

    if os.path.exists("docker-compose.yml"):
        logger.info("[PASS] docker-compose.yml found.")
        with open("docker-compose.yml", "r", encoding="utf-8") as f:
            if "depends_on" in f.read():
                logger.info("[PASS] 'depends_on' relation exists in docker-compose.yml.")
            else:
                logger.warning("[WARN] No 'depends_on' in docker-compose.yml, API might boot before DB.")
    else:
        logger.warning("[FAIL] docker-compose.yml is missing!")


def check_docker_compatibility_json() -> dict:
    """Returns docker compatibility check as a dict (used by /health endpoint)."""
    results = {}

    if os.path.exists("Dockerfile"):
        with open("Dockerfile", "r", encoding="utf-8") as f:
            content = f.read()
        results["platform_set"] = (
            "--platform=linux/amd64" in content or "--platform=linux/arm64" in content
        )
        results["entrypoint_ok"] = "uvicorn api:app" in content
    else:
        results["dockerfile"] = "missing"

    compose_file = None
    for name in ("docker-compose.yml", "docker-compose.yaml"):
        if os.path.exists(name):
            compose_file = name
            break

    if compose_file:
        with open(compose_file, "r", encoding="utf-8") as f:
            compose_content = f.read()
        results["compose_file"] = compose_file
        results["depends_on"] = "depends_on" in compose_content
        results["healthcheck_block"] = "healthcheck" in compose_content
        results["healthcheck_targets_health_route"] = (
            "healthcheck" in compose_content and "/health" in compose_content
        )
    else:
        results["compose_file"] = "missing"

    status = "fail" if "missing" in results.values() else "pass"
    return {"status": status, **results}


def main():
    parser = argparse.ArgumentParser(description="Full Project Health Analyzer & Cleanup")
    args = parser.parse_args()

    logger.info("==================================================")
    logger.info("        FLASK-AI HEALTH & DEPLOYMENT CHECK        ")
    logger.info("==================================================")

    check_env()
    check_dependencies()
    check_db_connection()
    check_docker_compatibility()

    logger.info("\n==================================================")
    logger.info("                 CHECK COMPLETE                   ")
    logger.info("==================================================")


if __name__ == "__main__":
    main()