import os
import re
import logging

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
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


# ── Request Models ─────────────────────────────────────────────────────────────
class StructureQuery(BaseModel):
    smiles: str = Field(
        ...,
        min_length=1,
        max_length=MAX_QUERY_LEN,
        description="SMILES string for structure search",
    )
    threshold: Optional[float] = Field(
        0.7,
        ge=0.0,
        le=1.0,
        description="Tanimoto similarity threshold (0.0 – 1.0)",
    )

    @field_validator("smiles")
    @classmethod
    def smiles_must_be_printable(cls, v: str) -> str:
        """Delegates to central validator; raises ValueError on bad input."""
        return validate_smiles(v)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/compounds/search")
@limiter.limit("60/minute")
async def search_compounds(
    request: Request,                                    
    q: Optional[str] = Query(None, max_length=MAX_QUERY_LEN, description="Name / CAS / CID / SMILES"),
    mwMin: Optional[float] = Query(None, ge=0.0, description="Min molecular weight"),
    mwMax: Optional[float] = Query(None, ge=0.0, description="Max molecular weight"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    _key: str = Depends(verify_api_key),
):
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


@app.post("/compounds/structure/exact")
@limiter.limit("30/minute")
async def exact_structure_search(
    request: Request,
    query: StructureQuery,
    _key: str = Depends(verify_api_key),
):
    try:
        df = search_molecules(smiles=query.smiles, search_mode="exact", limit=200)
        if df is None:
            raise HTTPException(status_code=503, detail="Database unavailable")
        return df.to_dict(orient="records")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in exact_structure_search: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/compounds/structure/substructure")
@limiter.limit("30/minute")
async def substructure_search(
    request: Request,
    query: StructureQuery,
    _key: str = Depends(verify_api_key),
):
    try:
        df = search_molecules(smiles=query.smiles, search_mode="substructure", limit=200)
        if df is None:
            raise HTTPException(status_code=503, detail="Database unavailable")
        return df.to_dict(orient="records")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in substructure_search: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/compounds/structure/similarity")
@limiter.limit("30/minute")
async def similarity_search(
    request: Request,
    query: StructureQuery,
    _key: str = Depends(verify_api_key),
):
    try:
        df = search_molecules(
            smiles=query.smiles,
            search_mode="similarity",
            similarity_threshold=query.threshold,
            limit=200,
        )
        if df is None:
            raise HTTPException(status_code=503, detail="Database unavailable")
        return df.to_dict(orient="records")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in similarity_search: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/health")
async def health():
    return {"status": "ok"}
