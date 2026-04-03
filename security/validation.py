MAX_QUERY_LEN: int = 512

def validate_text_query(value: str) -> str:
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
