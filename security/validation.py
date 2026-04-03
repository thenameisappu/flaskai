MAX_QUERY_LEN: int = 512

def validate_text_query(value: str) -> str:
    """
    Validate and sanitize a free-text search query.

    Raises:
        ValueError: if input exceeds MAX_QUERY_LEN or contains control characters.
    Returns:
        The stripped, validated string (empty string if input is falsy).
    """
    if not value:
        return ""
    value = value.strip()
    if len(value) > MAX_QUERY_LEN:
        raise ValueError(
            f"Search query is too long (max {MAX_QUERY_LEN} characters)."
        )
    if any(ord(c) < 32 and c not in ("\t",) for c in value):
        raise ValueError("Search query contains invalid control characters.")
    return value


def validate_smiles(value: str) -> str:
    """
    Validate a SMILES string: non-empty, bounded length, printable characters only.

    Raises:
        ValueError: if the SMILES is empty, too long, or contains control characters.
    Returns:
        The stripped, validated SMILES string.
    """
    value = (value or "").strip()
    if not value:
        raise ValueError("SMILES string cannot be empty.")
    if len(value) > MAX_QUERY_LEN:
        raise ValueError(
            f"SMILES string is too long (max {MAX_QUERY_LEN} characters)."
        )
    if any(ord(c) < 32 and c not in ("\t",) for c in value):
        raise ValueError("SMILES contains invalid control characters.")
    return value
