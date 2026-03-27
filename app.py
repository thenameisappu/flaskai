import streamlit as st
from streamlit_ketcher import st_ketcher

from rdkit import Chem
from rdkit.Chem import Draw, Descriptors

from db_search import search_molecules
from normalization import generate_canonical_key


st.set_page_config(layout="wide")

st.title("🧪 Molecule Dashboard")

# =========================
# Draw molecule section
# =========================

smiles = st_ketcher()


# =========================
# Unified Search section
# =========================

st.header("🔍 Molecular Search")

# Search mode selector
search_mode = st.selectbox(
    "Structure Search Mode",
    ["exact", "substructure", "similarity"]
)

similarity_threshold = 0.7

if search_mode == "similarity":
    similarity_threshold = st.slider(
        "Similarity Threshold",
        0.1, 1.0, 0.7
    )

# Single universal search box
query = st.text_input(
    "Search by Name, CAS Number, Alternative Name, CID, or SMILES"
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


# =========================
# Unified Search Functionality
# =========================

def perform_search(smiles, query, minWeight, maxWeight, search_mode, similarity_threshold):
    # Convert defaults to None
    minW = minWeight if minWeight != 0 else None
    maxW = maxWeight if maxWeight != 0 else None

    # Auto-detect search type
    cid = None
    iupacName = None
    casNumber = None
    altName = None

    from rdkit import RDLogger
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

        # 1. SMILES detection (priority)
        if query_mol and query_mol.GetNumAtoms() > 0:
            smiles = query
        elif looks_like_smiles:
            st.warning("Invalid SMILES string provided.")
            return
        # 2. CID detection
        elif query.isdigit():
            cid = int(query)
        # 3. CAS detection (example: 50-78-2)
        elif "-" in query:
            casNumber = query
        # 4. Name search fallback
        else:
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
                    st.write("Smlies:", smiles_str)
                    img = Draw.MolToImage(mol, size=(300, 300))
                    st.image(img, caption=row.get("iupacName") or row.get("iupacname", "Unknown Molecule"))
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

# =========================
# Trigger Logic
# =========================

# Initialize session state for tracking SMILES changes
if "last_smiles" not in st.session_state:
    st.session_state.last_smiles = None

# Detect if "Apply" was clicked in Ketcher (smiles changed)
auto_trigger = False
if smiles and smiles != st.session_state.last_smiles:
    st.session_state.last_smiles = smiles
    auto_trigger = True

if st.button("Search Molecules") or auto_trigger:
    perform_search(smiles, query, minWeight, maxWeight, search_mode, similarity_threshold)
    