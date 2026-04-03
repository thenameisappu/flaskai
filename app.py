import time
import html
import streamlit as st
from streamlit_ketcher import st_ketcher

from rdkit import Chem
from rdkit.Chem import Draw, Descriptors
import re

from db_search import search_molecules
from normalization import generate_canonical_key
from security.validation import validate_text_query

st.set_page_config(layout="wide")

st.title("🧪 Molecule Dashboard")
smiles = st_ketcher()


st.header("🔍 Molecular Search")

search_mode = st.selectbox(
    "Search Mode",
    ["exact", "substructure", "similarity"]
)

similarity_threshold = 0.7

if search_mode == "similarity":
    similarity_threshold = st.slider(
        "Similarity Threshold",
        0.1, 1.0, 0.7
    )

query = st.text_input(
    "Search Box"
)

col1, col2 = st.columns(2)

with col1:
    minWeight = st.number_input(
        "Min Molecular Weight",
        min_value=0.0,
        step=0.1
    )

with col2:
    maxWeight = st.number_input(
        "Max Molecular Weight",
        min_value=0.0,
        step=0.1
    )


def perform_search(smiles, query, minWeight, maxWeight, search_mode, similarity_threshold):
    from rdkit import RDLogger

    try:
        query = validate_text_query(query)
    except ValueError as e:
        st.warning(str(e))
        return

    minW = minWeight if minWeight != 0 else None
    maxW = maxWeight if maxWeight != 0 else None

    cid = None
    iupacName = None
    casNumber = None
    altName = None

    cas_pattern = r'^\d{2,7}-\d{2}-\d$'

    if smiles:
        RDLogger.DisableLog('rdApp.*')
        check_mol = Chem.MolFromSmiles(smiles)
        RDLogger.EnableLog('rdApp.*')
        if not check_mol:
            st.warning("Invalid SMILES string from Ketcher.")
            return

    if query:
        RDLogger.DisableLog('rdApp.*')
        query_mol = Chem.MolFromSmiles(query)
        RDLogger.EnableLog('rdApp.*')
        
        looks_like_smiles = any(c in query for c in "#()[]=@") and not query.isdigit()

        if query_mol and query_mol.GetNumAtoms() > 0:
            smiles = query
        elif looks_like_smiles:
            st.warning("Invalid SMILES string provided.")
            return

        elif query.isdigit():
            cid = query  

        elif re.match(cas_pattern, query):
            casNumber = query

        else:
            casNumber = query
            iupacName = query
            altName = query

    results = search_molecules(
        smiles=smiles,
        iupacName=iupacName,
        casNumber=casNumber,
        altName=altName,
        cid=cid,
        minWeight=minW,
        maxWeight=maxW,
        search_mode=search_mode,
        similarity_threshold=similarity_threshold
    )

    if results is None:
        st.error("🚨 Connection Error: Unable to reach the molecular database.")
    elif len(results) > 0:
        st.success(f"{len(results)} molecules found")
        st.dataframe(results, width='stretch')
        st.subheader("Structures")

        for _, row in results.iterrows():
            mol_block = row.get("structureMol") or row.get("structuremol")
            smiles_str = row.get("smiles")

            mol = None
            if mol_block:
                mol = Chem.MolFromMolBlock(mol_block)
            
            if not mol and smiles_str:
                mol = Chem.MolFromSmiles(smiles_str)

            if mol:
                res_col1, res_col2 = st.columns(2)
                with res_col1:
                    safe_smiles = html.escape(str(smiles_str)) if smiles_str else ""
                    st.write("SMILES:", safe_smiles)
                    img = Draw.MolToImage(mol, size=(300, 300))
                    safe_caption = html.escape(str(row.get("iupacName") or row.get("iupacname", "Unknown Molecule")))
                    st.image(img, caption=safe_caption)
                with res_col2:
                    st.subheader("Properties")
                    
                    # Generate identical unique codes based off name to prove equivalency
                    chemical_name = row.get("iupacName") or row.get("iupacname", "Unknown Molecule")
                    canonical_id = generate_canonical_key(chemical_name)
                    st.write("Unique Compound ID:")
                    st.code(canonical_id, language=None)
                    
                    if smiles_str:
                        st.write("Molecular Weight:", round(Descriptors.MolWt(mol), 2))
                    st.write("LogP:", round(Descriptors.MolLogP(mol), 2))
                    st.write("Atoms:", mol.GetNumAtoms())
    else:
        st.warning("Compound not found")


if "last_smiles" not in st.session_state:
    st.session_state.last_smiles = None

# Session-state rate limiting: prevent more than 1 search per 2 seconds.
_MIN_SEARCH_INTERVAL = 2.0
if "last_search_time" not in st.session_state:
    st.session_state.last_search_time = 0.0

auto_trigger = False
if smiles and smiles != st.session_state.last_smiles:
    st.session_state.last_smiles = smiles
    auto_trigger = True

if st.button("Search Molecules") or auto_trigger:
    elapsed = time.time() - st.session_state.last_search_time
    if elapsed < _MIN_SEARCH_INTERVAL:
        st.warning(
            f"Please wait {_MIN_SEARCH_INTERVAL - elapsed:.1f}s before searching again."
        )
    else:
        st.session_state.last_search_time = time.time()
        perform_search(smiles, query, minWeight, maxWeight, search_mode, similarity_threshold)
 
