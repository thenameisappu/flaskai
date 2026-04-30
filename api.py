import os, re, logging, math
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

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Molecule Search API", openapi_url="/openapi.json")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_allowed_origins, allow_credentials=False,
                   allow_methods=["GET", "POST"], allow_headers=["X-API-Key", "Content-Type"])

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        r = await call_next(request)
        r.headers.update({"Strict-Transport-Security": "max-age=31536000; includeSubDomains",
                           "Content-Security-Policy": "default-src 'self'",
                           "X-Content-Type-Options": "nosniff",
                           "X-Frame-Options": "DENY", "X-XSS-Protection": "1; mode=block"})
        return r

app.add_middleware(SecurityHeadersMiddleware)
verify_api_key = get_verify_api_key_dependency(required_role="user")


def _safe_sim(v) -> float:
    try:
        f = float(v)
        return 0.0 if math.isnan(f) else f
    except (TypeError, ValueError):
        return 0.0


def _run_structure_searches(smiles: str, threshold: float, kwargs: dict) -> pd.DataFrame:
    frames = []
    for mode in ("exact", "substructure", "similarity"):
        try:
            kw = {**kwargs, **({"similarity_threshold": threshold} if mode == "similarity" else {})}
            df = search_molecules(smiles=smiles, search_mode=mode, **kw)
            if df is not None and not df.empty:
                df = df.copy()
                df["match_types"] = [[mode]] * len(df)
                frames.append(df)
        except Exception as e:
            logger.warning("%s search failed: %s", mode, e)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    id_col = "cid" if "cid" in combined.columns else "inchikey"
    seen: dict = {}

    for row in combined.to_dict(orient="records"):
        key = row.get(id_col)
        if key is None:
            continue
        sim_val = row.get("similarity")
        is_sim = sim_val is not None and not (isinstance(sim_val, float) and math.isnan(sim_val))
        if key not in seen:
            seen[key] = {**row, "match_types": list(row["match_types"])}
            if is_sim:
                seen[key]["similarity_score"] = _safe_sim(sim_val)
        else:
            seen[key]["match_types"] = sorted(set(seen[key]["match_types"]) | set(row["match_types"]))
            if is_sim:
                seen[key]["similarity_score"] = max(seen[key].get("similarity_score", 0.0), _safe_sim(sim_val))

    merged = list(seen.values())
    for r in merged:
        r.pop("similarity", None)

    if not merged:
        return pd.DataFrame()

    priority = {"exact": 0, "substructure": 1, "similarity": 2}
    df = pd.DataFrame(merged)
    df = df.iloc[sorted(range(len(df)),
                        key=lambda i: (min(priority.get(t, 9) for t in df.iloc[i]["match_types"]),
                                       -(df.iloc[i].get("similarity_score") or 0.0)))
                 ].reset_index(drop=True)
    return df


@app.get("/compounds/search")
@limiter.limit("60/minute")
async def search_compounds(
    request: Request,
    q: Optional[str] = Query(None, max_length=MAX_QUERY_LEN, description="Name / CAS / CID"),
    mwMin: Optional[float] = Query(None, ge=0.0),
    mwMax: Optional[float] = Query(None, ge=0.0),
    smiles: Optional[str] = Query(None, max_length=MAX_QUERY_LEN, description="SMILES string for structural search"),
    searchMode: Optional[str] = Query(None, description="exact | substructure | similarity — omit for all three"),
    threshold: float = Query(0.7, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    _key: str = Depends(verify_api_key),
):
    try:
        cid = iupacName = casNumber = altName = None
        cas_pattern = r'^\d{2,7}-\d{2}-\d$'

        if q:
            q = validate_text_query(q)
            if q.isdigit():
                cid = q
            elif re.match(cas_pattern, q):
                casNumber = q
            else:
                iupacName = altName = q

        if smiles:
            smiles = validate_smiles(smiles)
            valid_modes = {"exact", "substructure", "similarity"}
            if searchMode and searchMode not in valid_modes:
                raise ValueError(f"Invalid searchMode. Choose from: {', '.join(valid_modes)}")

            kwargs = dict(iupacName=iupacName, altName=altName, casNumber=casNumber,
                          cid=cid, minWeight=mwMin, maxWeight=mwMax, limit=limit, offset=0)

            if searchMode:
                df = search_molecules(smiles=smiles, search_mode=searchMode,
                                      similarity_threshold=threshold, **kwargs)
                if df is None:
                    raise HTTPException(status_code=503, detail="Database unavailable")
                if not df.empty:
                    df = df.copy()
                    df["match_types"] = [[searchMode]] * len(df)
                    if "similarity" in df.columns:
                        df["similarity_score"] = df["similarity"].apply(_safe_sim)
                        df = df.drop(columns=["similarity"])
                df = df.iloc[offset: offset + limit]
            else:
                df = _run_structure_searches(smiles, threshold, kwargs)
                if df is None:
                    raise HTTPException(status_code=503, detail="Database unavailable")
                df = df.iloc[offset: offset + limit]
        else:
            df = search_molecules(iupacName=iupacName, altName=altName, casNumber=casNumber,
                                  cid=cid, minWeight=mwMin, maxWeight=mwMax, limit=limit, offset=offset)
            if df is None:
                raise HTTPException(status_code=503, detail="Database unavailable")

        records = df.to_dict(orient="records")
        for r in records:
            r.pop("match_types", None)
            if "similarity_score" in r:
                r["similarity_score"] = round(float(r["similarity_score"]), 4)
        return records

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error("Error in search_compounds: %s — %s", type(e).__name__, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.get("/health")
async def health():
    checks = {"1_environment": check_env_json(), "2_dependencies": check_dependencies_json(),
              "3_database": check_db_connection_json(), "4_docker": check_docker_compatibility_json()}
    overall = "pass" if all(c.get("status") in ("pass", "warn") for c in checks.values()) else "fail"
    return {"status": overall, "checks": checks}
