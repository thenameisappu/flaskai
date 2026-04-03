import os
import logging
import psycopg2
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Required environment variables — NO fallback for secrets.
_REQUIRED_DB_VARS = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]


def _get_db_config() -> dict:
    """Read DB config from environment. Raises RuntimeError if any required var is missing."""
    missing = [v for v in _REQUIRED_DB_VARS if not os.getenv(v)]
    if missing:
        raise RuntimeError(
            f"Missing required database environment variables: {', '.join(missing)}. "
            "Set them in your .env file (see .env.example)."
        )
    return {
        "host": os.getenv("DB_HOST"),
        "dbname": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "port": os.getenv("DB_PORT"),
    }


def get_connection():
    try:
        config = _get_db_config()
        conn = psycopg2.connect(**config)
        return conn
    except RuntimeError:
        raise
    except Exception as e:
        logger.error("Database connection failed. Check your DB_* environment variables.")
        raise