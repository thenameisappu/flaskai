import os
import re
import logging

import math
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from starlette.requests import Request
from starlette.middleware.base import BaseHTTPMiddleware
from dotenv import load_dotenv

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from db_search import search_molecules
from security.auth import get_verify_api_key_dependency
from security.validation import validate_text_query, validate_smiles, MAX_QUERY_LEN

from health_check import (
    check_env_json,
    check_dependencies_json,
    check_db_connection_json,
    check_docker_compatibility_json,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Rate Limiter ───────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── FastAPI App ────────────────────────────────────────────────────────────────
app = FastAPI(title="Molecule Search API", openapi_url="/openapi.json")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS Middleware ────────────────────────────────────────────────────────────
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
if not _allowed_origins:
    logger.warning(
        "ALLOWED_ORIGINS is not set — CORS will block all cross-origin requests."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["X-API-Key", "Content-Type"],
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# ── Auth ───────────────────────────────────────────────────────────────────────
verify_api_key = get_verify_api_key_dependency(required_role="user")


# ── Structure search helper ────────────────────────────────────────────────────

def _run_structure_searches(
    validated_smiles: str,
    threshold: float,
    shared_kwargs: dict,
) -> pd.DataFrame:
    """
    Run exact, substructure, and similarity searches and return a single
    deduplicated DataFrame with `match_types` and optional `similarity_score`.
    """
    frames = []

    # 1. Exact
    try:
        df_exact = search_molecules(smiles=validated_smiles, search_mode="exact", **shared_kwargs)
        if df_exact is not None and not df_exact.empty:
            df_exact = df_exact.copy()
            df_exact["match_types"] = [["exact"]] * len(df_exact)
            frames.append(df_exact)
    except Exception as e:
        logger.warning("Exact search failed: %s — %s", type(e).__name__, e)

    # 2. Substructure
    try:
        df_sub = search_molecules(smiles=validated_smiles, search_mode="substructure", **shared_kwargs)
        if df_sub is not None and not df_sub.empty:
            df_sub = df_sub.copy()
            df_sub["match_types"] = [["substructure"]] * len(df_sub)
            frames.append(df_sub)
    except Exception as e:
        logger.warning("Substructure search failed: %s — %s", type(e).__name__, e)

    # 3. Similarity
    try:
        df_sim = search_molecules(
            smiles=validated_smiles,
            search_mode="similarity",
            similarity_threshold=threshold,
            **shared_kwargs,
        )
        if df_sim is not None and not df_sim.empty:
            df_sim = df_sim.copy()
            df_sim["match_types"] = [["similarity"]] * len(df_sim)
            frames.append(df_sim)
    except Exception as e:
        logger.warning("Similarity search failed: %s — %s", type(e).__name__, e)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)

    # Deduplicate via plain dict loop — avoids pandas groupby/apply shape bugs
    id_col = "cid" if "cid" in combined.columns else "inchikey"
    has_sim_col = "similarity" in combined.columns

    def _safe_sim(val) -> float:
        """Convert a similarity value to float, treating None/NaN as 0.0."""
        try:
            f = float(val)
            return 0.0 if math.isnan(f) else f
        except (TypeError, ValueError):
            return 0.0

    seen: dict = {}
    for row in combined.to_dict(orient="records"):
        key = row.get(id_col)
        if key is None:
            continue
        is_sim_row = "similarity" in row and not (
            row["similarity"] is None or
            (isinstance(row["similarity"], float) and math.isnan(row["similarity"]))
        )
        if key not in seen:
            seen[key] = dict(row)
            seen[key]["match_types"] = list(row["match_types"])
            if is_sim_row:
                seen[key]["similarity_score"] = _safe_sim(row.get("similarity"))
        else:
            existing = seen[key]
            existing["match_types"] = sorted(
                set(existing["match_types"]) | set(row["match_types"])
            )
            if is_sim_row:
                existing["similarity_score"] = max(
                    existing.get("similarity_score", 0.0),
                    _safe_sim(row.get("similarity")),
                )

    merged_rows = list(seen.values())
    # Drop raw similarity column — we expose similarity_score instead
    for r in merged_rows:
        r.pop("similarity", None)

    if not merged_rows:
        return pd.DataFrame()

    deduped = pd.DataFrame(merged_rows)

    # Sort: exact first → substructure → similarity-only; highest score wins ties
    priority = {"exact": 0, "substructure": 1, "similarity": 2}

    def _sort_key(row):
        best = min(priority.get(t, 9) for t in row["match_types"])
        score = row.get("similarity_score", 0.0) or 0.0
        return (best, -score)

    deduped = deduped.iloc[
        sorted(range(len(deduped)), key=lambda i: _sort_key(deduped.iloc[i]))
    ].reset_index(drop=True)

    return deduped


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/compounds/search")
@limiter.limit("60/minute")
async def search_compounds(
    request: Request,
    # Text / metadata
    q: Optional[str] = Query(None, max_length=MAX_QUERY_LEN, description="Name / CAS / CID"),
    mwMin: Optional[float] = Query(None, ge=0.0, description="Min molecular weight"),
    mwMax: Optional[float] = Query(None, ge=0.0, description="Max molecular weight"),
    # Structure
    smiles: Optional[str] = Query(
        None,
        max_length=MAX_QUERY_LEN,
        description="SMILES string for structure search",
    ),
    searchMode: Optional[str] = Query(
        None,
        description="exact | substructure | similarity — omit to run all three",
    ),
    threshold: float = Query(
        0.7, ge=0.0, le=1.0,
        description="Tanimoto similarity threshold (default 0.7)",
    ),
    # Pagination
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    _key: str = Depends(verify_api_key),
):
    """
    Unified compound search.

    - **`q`** — text search by name, CAS, or CID
    - **`smiles`** + **`searchMode`** — run a specific mode (exact/substructure/similarity)
      or omit `searchMode` to run all three; results include `match_types` and `similarity_score`
    - Both can be combined with `mwMin` / `mwMax`
    """
    try:
        cid = None
        iupacName = None
        casNumber = None
        altName = None
        cas_pattern = r'^\d{2,7}-\d{2}-\d$'

        if q:
            original_q = validate_text_query(q)
            if original_q.isdigit():
                cid = int(original_q)
            elif re.match(cas_pattern, original_q):
                casNumber = original_q
            else:
                iupacName = original_q
                altName = original_q

        if smiles:
            validated_smiles = validate_smiles(smiles)

            # Validate searchMode if provided
            valid_modes = {"exact", "substructure", "similarity"}
            if searchMode and searchMode not in valid_modes:
                raise ValueError(f"Invalid searchMode '{searchMode}'. Choose from: exact, substructure, similarity")

            shared_kwargs = dict(
                iupacName=iupacName,
                altName=altName,
                casNumber=casNumber,
                cid=cid,
                minWeight=mwMin,
                maxWeight=mwMax,
                limit=limit,
                offset=0,  # paginate after dedup
            )

            if searchMode:
                # Run only the requested mode
                df = search_molecules(
                    smiles=validated_smiles,
                    search_mode=searchMode,
                    similarity_threshold=threshold,
                    **shared_kwargs,
                )
                if df is not None and not df.empty:
                    df = df.copy()
                    df["match_types"] = [[searchMode]] * len(df)
                    if "similarity" in df.columns:
                        df["similarity_score"] = df["similarity"].apply(
                            lambda v: 0.0 if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v)
                        )
                        df = df.drop(columns=["similarity"])
                if df is None:
                    raise HTTPException(status_code=503, detail="Database unavailable")
                df = df.iloc[offset: offset + limit]
            else:
                # Run all three modes and merge
                df = _run_structure_searches(validated_smiles, threshold, shared_kwargs)
                if df is None:
                    raise HTTPException(status_code=503, detail="Database unavailable")
                df = df.iloc[offset: offset + limit]

        else:
            df = search_molecules(
                iupacName=iupacName,
                altName=altName,
                casNumber=casNumber,
                cid=cid,
                minWeight=mwMin,
                maxWeight=mwMax,
                limit=limit,
                offset=offset,
            )

            if df is None:
                raise HTTPException(status_code=503, detail="Database unavailable")

        records = df.to_dict(orient="records")
        for r in records:
            r.pop("match_types", None)
            # Ensure similarity_score is a proper float (not int 0)
            if "similarity_score" in r:
                r["similarity_score"] = round(float(r["similarity_score"]), 4)
        return records

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error("Unhandled error in search_compounds: %s — %s", type(e).__name__, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.get("/health")
async def health():
    env    = check_env_json()
    deps   = check_dependencies_json()
    db     = check_db_connection_json()
    docker = check_docker_compatibility_json()

    overall = (
        "pass"
        if all(c.get("status") in ("pass", "warn") for c in [env, deps, db, docker])
        else "fail"
    )

    return {
        "status": overall,
        "checks": {
            "1_environment":  env,
            "2_dependencies": deps,
            "3_database":     db,
            "4_docker":       docker,
        },
    }