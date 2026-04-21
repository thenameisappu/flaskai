import os
import sys
import socket
import logging
import argparse
import psycopg2
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# ── Helpers ────────────────────────────────────────────────────────────────────

def _db_cfg() -> dict:
    """Read DB config purely from environment — no hardcoded fallbacks."""
    return {
        "host":     os.getenv("DB_HOST", ""),
        "port":     os.getenv("DB_PORT", ""),
        "dbname":   os.getenv("DB_NAME", ""),
        "user":     os.getenv("DB_USER", ""),
        "password": os.getenv("DB_PASSWORD", ""),
    }


def _step(label: str, ok: bool, detail: str = "") -> dict:
    return {"status": "pass" if ok else "fail", "detail": detail, "label": label}


def _filter_failed(steps: dict) -> dict:
    """Return only the steps that failed."""
    return {k: v for k, v in steps.items() if v["status"] == "fail"}


# ── Individual diagnostic steps ────────────────────────────────────────────────

def _check_env_vars(cfg: dict) -> dict:
    """Step 1 — Are all required env vars present and non-empty?"""
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        return _step(
            "env_vars",
            False,
            f"Missing or empty environment variables: {', '.join(missing).upper()}. "
            "Check your .env file."
        )
    return _step("env_vars", True, "All DB environment variables are set.")


def _check_host_dns(host: str, port: str) -> dict:
    """Step 2 — Can the hostname be resolved via DNS?"""
    try:
        resolved = socket.getaddrinfo(host, None)
        ip = resolved[0][4][0]
        return _step("host_dns", True, f"Host '{host}' resolved to {ip}.")
    except socket.gaierror as e:
        return _step(
            "host_dns",
            False,
            f"Cannot resolve host '{host}': {e}. "
            "Check DB_HOST in your .env — it may be a wrong hostname, typo, or the DB container is not running."
        )


def _check_port_reachable(host: str, port: str) -> dict:
    """Step 3 — Is the port open / reachable (TCP connect)?"""
    try:
        p = int(port)
    except (ValueError, TypeError):
        return _step("port_reachable", False, f"DB_PORT '{port}' is not a valid integer.")

    try:
        with socket.create_connection((host, p), timeout=5):
            pass
        return _step("port_reachable", True, f"Port {p} on '{host}' is open.")
    except (ConnectionRefusedError, OSError) as e:
        return _step(
            "port_reachable",
            False,
            f"Cannot reach {host}:{p} — {e}. "
            "Ensure the database container/service is running and the port is correct (DB_PORT)."
        )


def _check_db_connect(cfg: dict) -> dict:
    """Step 4 — Can psycopg2 open a connection (auth + database name)?"""
    try:
        conn = psycopg2.connect(
            host=cfg["host"],
            port=cfg["port"],
            dbname=cfg["dbname"],
            user=cfg["user"],
            password=cfg["password"],
            connect_timeout=5,
        )
        conn.close()
        return _step(
            "db_connect",
            True,
            f"Connected to database '{cfg['dbname']}' as user '{cfg['user']}'."
        )
    except psycopg2.OperationalError as e:
        err = str(e).strip().replace("\n", " ")
        hint = ""
        if "password authentication failed" in err:
            hint = " → DB_PASSWORD is wrong."
        elif "database" in err and "does not exist" in err:
            hint = f" → Database '{cfg['dbname']}' does not exist. Check DB_NAME."
        elif "role" in err and "does not exist" in err:
            hint = f" → User '{cfg['user']}' does not exist. Check DB_USER."
        return _step("db_connect", False, f"Connection failed: {err}.{hint}")
    except Exception as e:
        return _step("db_connect", False, f"Unexpected error: {type(e).__name__}: {e}")


def _check_pg_version(conn) -> dict:
    """Step 5 — Query PostgreSQL version (sanity check)."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = str(cur.fetchone()[0])[:80]
        cur.close()
        return _step("pg_version", True, version)
    except Exception as e:
        return _step("pg_version", False, f"Could not query version: {e}")


def _check_rdkit_extension(conn) -> dict:
    """Step 6 — Is the RDKit extension enabled in this database?"""
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_extension WHERE extname='rdkit';")
        enabled = cur.fetchone() is not None
        cur.close()
        if enabled:
            return _step("rdkit_extension", True, "RDKit extension is enabled.")
        return _step(
            "rdkit_extension",
            False,
            "RDKit extension is NOT enabled. Run: CREATE EXTENSION IF NOT EXISTS rdkit; "
            "or rebuild with mcs07/postgres-rdkit image."
        )
    except Exception as e:
        return _step("rdkit_extension", False, f"Error checking RDKit: {e}")


def _check_molecules_table(conn) -> dict:
    """Step 7 — Does the configured MOLECULES_TABLE exist?"""
    table = os.getenv("MOLECULES_TABLE", "").strip().lower()
    if not table:
        return _step(
            "molecules_table",
            False,
            "MOLECULES_TABLE is not set in your .env file."
        )
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT to_regclass(%s);",
            (table,)
        )
        exists = cur.fetchone()[0] is not None
        cur.close()
        if exists:
            return _step("molecules_table", True, f"Table '{table}' exists.")
        return _step(
            "molecules_table",
            False,
            f"Table '{table}' does NOT exist in database '{os.getenv('DB_NAME')}'. "
            "Run init_db.py to create it, or check MOLECULES_TABLE in your .env."
        )
    except Exception as e:
        return _step("molecules_table", False, f"Error checking table: {e}")


def _check_table_row_count(conn) -> dict:
    """Step 8 — How many rows are in the molecules table (quick data check)?"""
    table = os.getenv("MOLECULES_TABLE", "").strip().lower()
    if not table:
        return _step("row_count", False, "MOLECULES_TABLE not set, skipping row count.")
    try:
        import re
        if not re.match(r'^[a-z0-9_]+$', table):
            return _step("row_count", False, f"Invalid table name format: '{table}'.")
        from psycopg2 import sql as psycopg2_sql
        cur = conn.cursor()
        cur.execute(psycopg2_sql.SQL("SELECT COUNT(*) FROM {}").format(psycopg2_sql.Identifier(table)))
        count = cur.fetchone()[0]
        cur.close()
        ok = count > 0
        msg = f"Table '{table}' contains {count} row(s)."
        if not ok:
            msg += " Table is empty — run seed_data.py to populate it."
        return _step("row_count", ok, msg)
    except Exception as e:
        return _step("row_count", False, f"Error counting rows: {e}")


# ── Public API (used by FastAPI /health endpoint) ──────────────────────────────

def check_db_connection_json() -> dict:
    """
    Runs all DB checks in sequence, stopping at the first failure.
    Returns only failed steps in the response.
    """
    cfg = _db_cfg()
    steps = {}

    s1 = _check_env_vars(cfg)
    steps["1_env_vars"] = s1
    if s1["status"] == "fail":
        return {"status": "fail", "summary": s1["detail"], "failed_steps": _filter_failed(steps)}

    s2 = _check_host_dns(cfg["host"], cfg["port"])
    steps["2_host_dns"] = s2
    if s2["status"] == "fail":
        return {"status": "fail", "summary": s2["detail"], "failed_steps": _filter_failed(steps)}

    s3 = _check_port_reachable(cfg["host"], cfg["port"])
    steps["3_port_reachable"] = s3
    if s3["status"] == "fail":
        return {"status": "fail", "summary": s3["detail"], "failed_steps": _filter_failed(steps)}

    s4 = _check_db_connect(cfg)
    steps["4_db_connect"] = s4
    if s4["status"] == "fail":
        return {"status": "fail", "summary": s4["detail"], "failed_steps": _filter_failed(steps)}

    try:
        conn = psycopg2.connect(
            host=cfg["host"], port=cfg["port"], dbname=cfg["dbname"],
            user=cfg["user"], password=cfg["password"], connect_timeout=5,
        )

        s5 = _check_pg_version(conn)
        steps["5_pg_version"] = s5

        s6 = _check_rdkit_extension(conn)
        steps["6_rdkit_extension"] = s6

        s7 = _check_molecules_table(conn)
        steps["7_molecules_table"] = s7

        s8 = _check_table_row_count(conn)
        steps["8_row_count"] = s8

        conn.close()
    except Exception as e:
        steps["5_open_connection"] = _step("open_connection", False, str(e))
        return {"status": "fail", "summary": str(e), "failed_steps": _filter_failed(steps)}

    failed = _filter_failed(steps)
    overall = "fail" if failed else "pass"
    summary = (
        "All database checks passed."
        if not failed
        else f"Failed steps: {', '.join(failed.keys())}"
    )

    result = {"status": overall, "summary": summary}
    if failed:
        result["failed_steps"] = failed
    return result


# ── Remaining /health check functions ─────────────────────────────────────────

def check_env_json() -> dict:
    load_dotenv()
    required_vars = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing = [v for v in required_vars if not os.getenv(v)]
    result = {
        "status": "pass" if not missing else "fail",
        "env_file_exists": os.path.exists(".env"),
    }
    if missing:
        result["missing_vars"] = missing
    return result


def check_dependencies_json() -> dict:
    dependencies = ["rdkit", "psycopg2", "fastapi", "pandas", "uvicorn"]
    missing = {}
    for dep in dependencies:
        try:
            __import__(dep)
        except ImportError:
            missing[dep] = "missing"
    result = {"status": "pass" if not missing else "fail"}
    if missing:
        result["missing_packages"] = missing
    return result


def check_docker_compatibility_json() -> dict:
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
    failed = {k: v for k, v in results.items() if v == "missing" or v is False}
    result = {"status": status}
    if failed:
        result["failures"] = failed
    return result


# ── CLI runner ─────────────────────────────────────────────────────────────────

def check_env():
    load_dotenv()
    required_vars = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        logger.warning("[FAIL] env_vars — Missing: %s", ', '.join(missing))
        return False
    return True


def check_dependencies():
    dependencies = ["rdkit", "psycopg2", "fastapi", "pandas", "uvicorn"]
    all_ok = True
    for dep in dependencies:
        try:
            __import__(dep)
        except ImportError:
            logger.warning("[FAIL] dependencies — %s is NOT installed.", dep)
            all_ok = False
    return all_ok


def check_db_connection():
    result = check_db_connection_json()
    for name, step in result.get("failed_steps", {}).items():
        logger.warning("[FAIL] %s — %s", step["label"], step["detail"])
    return result["status"] == "pass"


def check_docker_compatibility():
    r = check_docker_compatibility_json()
    if r["status"] == "fail":
        for k, v in r.get("failures", {}).items():
            logger.warning("[FAIL] docker — %s: %s", k, v)


def main():
    parser = argparse.ArgumentParser(description="FlaskAI Health Check")
    parser.parse_args()
    logger.info("=" * 50)
    logger.info("     MOLECULE API — HEALTH & DEPLOYMENT CHECK")
    logger.info("=" * 50)

    env_ok  = check_env()
    deps_ok = check_dependencies()
    db_ok   = check_db_connection()
    check_docker_compatibility()

    overall = all([env_ok, deps_ok, db_ok])
    if overall:
        logger.info("[OK] All checks passed.")
    else:
        logger.warning("[FAIL] One or more checks failed — see above.")

    logger.info("=" * 50)


if __name__ == "__main__":
    main()