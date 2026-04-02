from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging
import re

from db_search import search_molecules

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Molecule Search API")

class StructureQuery(BaseModel):
    smiles: str
    threshold: Optional[float] = 0.7


@app.get("/compounds/search")
async def search_compounds(
    q: Optional[str] = None,
    mwMin: Optional[float] = None,
    mwMax: Optional[float] = None,
    limit: int = 50,
    offset: int = 0
):
    try:
        cid = None
        iupacName = None
        casNumber = None
        altName = None
        
        cas_pattern = r'^\d{2,7}-\d{2}-\d$'

        if q:
            original_q = q.strip()

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
            maxWeight=mwMax
        )
        
        if df is None:
            raise HTTPException(status_code=500, detail="Database connection error")
            
        df = df.iloc[offset : offset + limit]
        
        return df.to_dict(orient="records")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in search_compounds: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


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
