import os
import re
import logging

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

from health_check import check_env_json, check_dependencies_json, check_db_connection_json, check_docker_compatibility_json

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Rate Limiter ───────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── FastAPI App ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Molecule Search API",
    openapi_url="/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS Middleware ────────────────────────────────────────────────────────────
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
if not _allowed_origins:
    logger.warning(
        "ALLOWED_ORIGINS is not set — CORS will block all cross-origin requests. "
        "Add ALLOWED_ORIGINS=http://your-frontend-host to .env"
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

# ── Auth Dependency ────────────────────────────────────────────────────────────
verify_api_key = get_verify_api_key_dependency(required_role="user")


# ── Routes ─────────────────────────────────────────────────────────────────────

def _run_structure_searches(
    validated_smiles: str,
    threshold: float,
    shared_kwargs: dict,
) -> pd.DataFrame:
    frames = []

    # ── 1. Exact ─────────────────────────────────────────────────────────────
    df_exact = search_molecules(smiles=validated_smiles, search_mode="exact", **shared_kwargs)
    if df_exact is not None and not df_exact.empty:
        df_exact = df_exact.copy()
        df_exact["match_types"] = [["exact"]] * len(df_exact)
        frames.append(df_exact)

    # ── 2. Substructure ───────────────────────────────────────────────────────
    df_sub = search_molecules(smiles=validated_smiles, search_mode="substructure", **shared_kwargs)
    if df_sub is not None and not df_sub.empty:
        df_sub = df_sub.copy()
        df_sub["match_types"] = [["substructure"]] * len(df_sub)
        frames.append(df_sub)

    # ── 3. Similarity ─────────────────────────────────────────────────────────
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

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)

    # Deduplicate on `cid` (or `inchikey` as fallback), merging match_types lists
    id_col = "cid" if "cid" in combined.columns else "inchikey"

    def _merge_group(group: pd.DataFrame) -> pd.Series:
        base = group.iloc[0].copy()
        all_types: list = []
        for mt in group["match_types"]:
            all_types.extend(mt)
        base["match_types"] = sorted(set(all_types))
        # Keep the best similarity score if present
        if "similarity" in group.columns:
            base["similarity_score"] = group["similarity"].max()
        return base

    deduped = (
        combined.groupby(id_col, sort=False)
        .apply(_merge_group)
        .reset_index(drop=True)
    )

    priority = {"exact": 0, "substructure": 1, "similarity": 2}

    def _sort_key(row):
        best = min(priority.get(t, 9) for t in row["match_types"])
        score = row.get("similarity_score", 0.0) or 0.0
        return (best, -score)

    deduped = deduped.iloc[
        sorted(range(len(deduped)), key=lambda i: _sort_key(deduped.iloc[i]))
    ].reset_index(drop=True)

    # Drop the internal similarity column if it came through from db_search
    if "similarity" in deduped.columns:
        deduped = deduped.drop(columns=["similarity"])

    return deduped


@app.get("/compounds/search")
@limiter.limit("60/minute")
async def search_compounds(
    request: Request,
    # ── Text / metadata filters ──────────────────────────────────────────────
    q: Optional[str] = Query(None, max_length=MAX_QUERY_LEN, description="Name / CAS / CID"),
    mwMin: Optional[float] = Query(None, ge=0.0, description="Min molecular weight"),
    mwMax: Optional[float] = Query(None, ge=0.0, description="Max molecular weight"),
    # ── Structure search ─────────────────────────────────────────────────────
    smiles: Optional[str] = Query(
        None,
        max_length=MAX_QUERY_LEN,
        description=(
            "SMILES string — automatically runs exact, substructure, and similarity "
            "searches and returns deduplicated results ranked by match type"
        ),
    ),
    threshold: float = Query(
        0.7,
        ge=0.0,
        le=1.0,
        description="Tanimoto similarity threshold used for the similarity pass (default 0.7)",
    ),
    # ── Pagination ───────────────────────────────────────────────────────────
    limit: int = Query(50, ge=1, le=200, description="Max results per search mode"),
    offset: int = Query(0, ge=0, description="Pagination offset (applied after deduplication)"),
    _key: str = Depends(verify_api_key),
):
    
    try:
        cid = None
        iupacName = None
        casNumber = None
        altName = None

        cas_pattern = r'^\d{2,7}-\d{2}-\d$'

        # ── Parse text query ─────────────────────────────────────────────────
        if q:
            original_q = validate_text_query(q)
            if original_q.isdigit():
                cid = int(original_q)
            elif re.match(cas_pattern, original_q):
                casNumber = original_q
            else:
                iupacName = original_q
                altName = original_q

        # ── Structure search (all three modes) ───────────────────────────────
        if smiles:
            validated_smiles = validate_smiles(smiles)

            # Shared keyword args forwarded to every search_molecules call.
            # Pagination is intentionally omitted here — we paginate AFTER
            # deduplication so the caller always sees a stable page slice.
            shared_kwargs = dict(
                iupacName=iupacName,
                altName=altName,
                casNumber=casNumber,
                cid=cid,
                minWeight=mwMin,
                maxWeight=mwMax,
                limit=limit,
                offset=0,
            )

            df = _run_structure_searches(validated_smiles, threshold, shared_kwargs)

            if df is None:
                raise HTTPException(status_code=503, detail="Database unavailable")

            # Apply pagination after merge + dedup
            df = df.iloc[offset: offset + limit]

        # ── Text / metadata only ─────────────────────────────────────────────
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

        return df.to_dict(orient="records")

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error("Error in search_compounds: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Internal server error")


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