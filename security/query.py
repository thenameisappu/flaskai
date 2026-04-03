import re

_LIKE_ESCAPE_CHAR = "!"

def escape_like(value: str) -> str:
    """
    Escape PostgreSQL LIKE metacharacters in a user-supplied string.

    Always pair this with  ESCAPE '!'  in the SQL clause:
        column LIKE %s ESCAPE '!'

    Escapes: ! → !!   % → !%   _ → !_
    This prevents users from injecting arbitrary LIKE wildcards.
    """
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
    conditions = []
    params = []

    for k, v in filters.items():
        conditions.append(f"{k} = %s")
        params.append(v)

    sql = f"SELECT * FROM {table}"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    return sql, params
