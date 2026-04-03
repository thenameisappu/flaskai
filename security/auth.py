import os
import hashlib
import hmac
import logging

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

def _load_api_key_hashes() -> dict:
    """
    Read comma-separated API key hashes from the API_KEY_HASHES environment variable.
    Format should be: <sha256_hash>:<role>,<sha256_hash>:<role>
    If no role is provided, defaults to 'user'.
    """
    raw = os.getenv("API_KEY_HASHES", "")
    key_map = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        hash_val = parts[0].strip()
        role = parts[1].strip() if len(parts) > 1 else "user"
        key_map[hash_val] = role

    if not key_map:
        logger.warning(
            "API_KEY_HASHES is not set — every API request will be rejected. "
            "Add API_KEY_HASHES=<your-sha256-hash>:admin to your .env file."
        )
    return key_map

_VALID_API_HASHES: dict = _load_api_key_hashes()

def get_verify_api_key_dependency(required_role: str = None):
    """
    Build and return the FastAPI Security dependency that validates X-API-Key natively.
    Uses HMAC comparison on a dynamically generated SHA-256 to prevent timing attacks.
    """
    from fastapi import HTTPException, Depends
    from fastapi.security.api_key import APIKeyHeader

    _header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)

    async def _verify(api_key: str = Depends(_header_scheme)) -> str:
        if not api_key:
            logger.warning("API request rejected: missing API key.")
            raise HTTPException(
                status_code=401,
                detail="Missing API key.",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        # Hash incoming key for safe comparison
        incoming_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
        
        # Prevent timing attacks across our known hashes
        authenticated_role = None
        for safe_hash, role in _VALID_API_HASHES.items():
            if hmac.compare_digest(incoming_hash, safe_hash):
                authenticated_role = role
                break

        if not authenticated_role:
            logger.warning("API request rejected: invalid API key.")
            raise HTTPException(
                status_code=401,
                detail="Invalid API key.",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        if required_role and authenticated_role != required_role and authenticated_role != "admin":
            logger.warning(f"API request rejected: missing required role '{required_role}'.")
            raise HTTPException(
                status_code=403,
                detail="Insufficient permissions.",
            )

        return api_key

    return _verify
