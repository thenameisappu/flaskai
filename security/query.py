import re
from psycopg2 import sql as psycopg2_sql

ALLOWED_TABLES = {"users", "products", "orders", "molecules", "compounds", "test_molecules", "production_molecules"}
ALLOWED_COLUMNS = {"name", "alternativenames", "id", "smiles", "cid", "iupacname", "casnumber", "inchikey", "molweight"}

_LIKE_ESCAPE_CHAR = "!"

def escape_like(value: str) -> str:
    return (
        value
        .replace(_LIKE_ESCAPE_CHAR, _LIKE_ESCAPE_CHAR * 2)
        .replace("%",               _LIKE_ESCAPE_CHAR + "%")
        .replace("_",               _LIKE_ESCAPE_CHAR + "_")
    )

def safe_query(table: str, filters: dict):
    """
    Constructs a basic safe SQL query using explicit string arrays.
    For db_search.py, we directly leverage psycopg2.sql for AST evaluation.
    This acts as a standardized template for future basic reads.
    """
    if table not in ALLOWED_TABLES:
        raise ValueError("Invalid table name")

    conditions = []
    params = []

    for k, v in filters.items():
        if k not in ALLOWED_COLUMNS:
            raise ValueError("Invalid column name")
        conditions.append(psycopg2_sql.SQL("{} = %s").format(psycopg2_sql.Identifier(k)))
        params.append(v)

    query = psycopg2_sql.SQL("SELECT * FROM {}").format(psycopg2_sql.Identifier(table))
    if conditions:
        query += psycopg2_sql.SQL(" WHERE ") + psycopg2_sql.SQL(" AND ").join(conditions)

    return query, params
