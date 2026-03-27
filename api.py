from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import logging

from db_search import search_molecules

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Molecule Search API")

# =========================
# Request models
# =========================

class StructureQuery(BaseModel):
    smiles: str
    threshold: Optional[float] = 0.7


# =========================
# TEXT SEARCH
# =========================

@app.get("/compounds/search")
async def search_compounds(
    q: Optional[str] = None,
    mwMin: Optional[float] = None,
    mwMax: Optional[float] = None,
    limit: int = 50,
    offset: int = 0
):
    try:
        # Use centralized search logic
        df = search_molecules(
            search=q,
            iupacName=q,
            altName=q,
            casNumber=q,
            minWeight=mwMin,
            maxWeight=mwMax
        )
        
        if df is None:
            raise HTTPException(status_code=500, detail="Database connection error")
            
        # Apply limit and offset (since search_molecules doesn't currently handle them)
        df = df.iloc[offset : offset + limit]
        
        return df.to_dict(orient="records")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in search_compounds: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# =========================
# EXACT STRUCTURE SEARCH
# =========================

@app.post("/compounds/structure/exact")
async def exact_structure_search(query: StructureQuery):
    try:
        df = search_molecules(smiles=query.smiles, search_mode="exact")
        if df is None:
            raise HTTPException(status_code=500, detail="Database connection error")
        return df.to_dict(orient="records")
    except Exception as e:
        logger.error(f"Error in exact_structure_search: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# =========================
# SUBSTRUCTURE SEARCH
# =========================

@app.post("/compounds/structure/substructure")
async def substructure_search(query: StructureQuery):
    try:
        df = search_molecules(smiles=query.smiles, search_mode="substructure")
        if df is None:
            raise HTTPException(status_code=500, detail="Database connection error")
        return df.to_dict(orient="records")
    except Exception as e:
        logger.error(f"Error in substructure_search: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# =========================
# SIMILARITY SEARCH
# =========================

@app.post("/compounds/structure/similarity")
async def similarity_search(query: StructureQuery):
    try:
        df = search_molecules(
            smiles=query.smiles, 
            search_mode="similarity", 
            similarity_threshold=query.threshold
        )
        if df is None:
            raise HTTPException(status_code=500, detail="Database connection error")
        return df.to_dict(orient="records")
    except Exception as e:
        logger.error(f"Error in similarity_search: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
