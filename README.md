# 🧪 Molecule Dashboard

A robust web application for molecular structure search, property calculation, and visualization. Built with Streamlit, FastAPI, RDKit, and PostgreSQL (rdkit-postgres).

## 🚀 Getting Started

### Prerequisites
- Docker and Docker Compose
- (Optional) Python 3.9+ for local development

### Quick Start with Docker
1. Clone the repository.
2. Ensure you have a `.env` file (copied from `.env.example`).
3. Build and start the containers:
   ```bash
   docker-compose up --build
   ```
4. Initialize the database (first-time only):
   ```bash
   docker-compose exec api python init_db.py
   ```
5. Access the applications:
   - **Main UI (Streamlit)**: `http://localhost:8501`
   - **API Documentation (FastAPI)**: `http://localhost:8000/docs`
   - **Database Management (pgAdmin)**: `http://localhost:8080` (admin@email.com / admin)

## 📁 Project Structure
- `App.py`: Main Streamlit dashboard.
- `api.py`: FastAPI backend for structure and text searches.
- `db_search.py`: Core search logic using RDKit and SQL.
- `db.py`: Database connection management.
- `init_db.py`: Schema initialization script.
- `schema.sql`: PostgreSQL/RDKit database schema.
- `Dockerfile`: Multi-service Docker configuration.
- `docker-compose.yml`: Orchestration for app, API, and DB.

## 🛠️ Features
- **SMILES Visualization**: Draw or paste SMILES to see 2D representation and properties.
- **Molecular Search**: Integrated search by Name, CAS Number, CID, or weight.
- **Structure Search**: Support for Exact, Substructure, and Similarity (Tanimoto) searches.
- **Robustness**: Enhanced with environment-based configuration and error handling.
