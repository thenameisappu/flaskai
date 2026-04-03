# 🧪 Molecule Search API & Dashboard (FlaskAI)

## 🚀 Overview

The Molecule Search API & Dashboard is a full-stack, state-of-the-art chemical informatics platform designed to power advanced molecular searches. By uniting a modern Streamlit frontend with a high-performance FastAPI back-end, it empowers researchers and developers to search, visualize, and analyze molecular compounds effortlessly.

At its core, the project solves the complex challenge of chemical identification and structural matching by leveraging RDKit and a customized PostgreSQL database. It supports advanced structure-based queries—like exact match, substructure matching, and Tanimoto similarity—while also offering comprehensive text-based search (SMILES, IUPAC, CAS, and common names) paired with robust chemical name normalization.

## 🧠 Features

* **Advanced Structural Search**: Perform Exact, Substructure, and Similarity (Tanimoto) searches.
* **Interactive Chemical Drawing**: Integrated Ketcher tool for drawing molecules directly in the browser.
* **Flexible Text Search**: Query by CAS Number, IUPAC Name, alternate names, CID, or SMILES.
* **Smart Chemical Normalization**: Automatically normalizes Greek letters (e.g., α to alpha) and generates deterministic, canonical SHA-256 chemical hashes to identify compounds seamlessly.
* **Property Calculation on the Fly**: Computes Molecular Weight, LogP, and Atom Counts natively using RDKit.
* **High-Performance Database Layer**: Utilizes PostgreSQL with native RDKit extensions for lightning-fast, DB-level chemical filtering, with an automated fallback to Python-level processing.
* **Dynamic Visualization**: Renders high-quality 2D chemical structures.

## 🏗️ Architecture

The system is built on a service-oriented architecture ensuring high scalability, strong security, and clear separation of concerns.

* **Frontend Layer (`app.py`)**: A Streamlit application offering a rich UI. It communicates with the database search logical modules, validating inputs before requests are evaluated.
* **API Layer (`api.py`)**: A fast, asynchronous REST API powered by FastAPI. Handles routing, rate limiting, and core security checks.
* **Business & Database Layer (`db.py`, `db_search.py`)**: Manages secure connection pooling and constructs dynamic, SQL-injection-safe queries. Determines whether DB-level or Python-level structural filtering is required.
* **Normalization & Security (`normalization.py`, `security/`)**: Normalizes complex chemical inputs and enforces strict authentication, query escaping, and input validation bounds.

**Execution Flow:**
Input (Drawing / Text string) → API / UI Request → Input Validation & Normalization → Parameterized SQL Query Generation → PostgreSQL Execution (RDKit Ext.) → Python-level filtering (Fallback) → Data Structuring → Output (Metrics & 2D render)

## 📂 Project Structure

```text
FlaskAI/
├── app.py                   # Streamlit interactive application
├── api.py                   # FastAPI REST API endpoints
├── db.py                    # Database connection setup & configuration
├── db_search.py             # Core molecular querying logic
├── normalization.py         # Chemical nomenclature normalization & hashing
├── security/                # Security modules
│   ├── auth.py              # API Key and role-based authentication
│   ├── query.py             # SQL wildcard/LIKE string escaping 
│   └── validation.py        # Bound checking & payload neutralization
├── .env.example             # Environment variable templates
├── requirements.txt         # Python dependencies
├── Dockerfile               # Production multi-service Docker image setup
└── docker-compose.yml       # Orchestration for API, App, DB, and pgAdmin
```

## ⚙️ Installation

### Prerequisites
* Docker & Docker Compose
* (Optional) Python 3.9+ for local non-Docker development

### 1. Clone & Configure
Copy the example environment variables and customize them.
```bash
cp .env.example .env
```
*(Configure `DB_PASSWORD`, `API_KEYS`, and `ALLOWED_ORIGINS` according to your specific environment within `.env`)*

### 2. Run with Docker Compose
The system is fully containerized. A single command handles the database, API, web app, and pgAdmin.
```bash
docker-compose up --build -d
```

## ▶️ Usage

Once the containers are running, the services are available at:

* **Streamlit Dashboard**: [http://localhost:8501](http://localhost:8501)
* **REST API**: [http://localhost:8000](http://localhost:8000)
    * *API Documentation (OpenAPI)*: Available at `http://localhost:8000/docs`
* **pgAdmin Database Dashboard**: [http://localhost:8080](http://localhost:8080)

### Example API Request (cURL)
```bash
curl -X 'GET' \
  'http://localhost:8000/compounds/search?q=aspirin&limit=10' \
  -H 'accept: application/json' \
  -H 'X-API-Key: YOUR_API_KEY_HERE'
```

## 🔐 Security

Security is deeply integrated directly into the infrastructure:

* **SQL Injection Prevention**: Relies strictly on `psycopg2.sql` for query generation with parameterization. No vulnerable string concatenations are utilized.
* **Wildcard Exploitation Protection**: Implements custom `ESCAPE` character pairing (`security/query.py`) to prevent arbitrary LIKE wildcard injections.
* **Authentication**: Utilizes SHA-256 comparisons secured against timing-attacks natively via HMAC (`security/auth.py`). 
* **Input Validation**: Limits maximum query spans and strips malicious control characters (`security/validation.py`) to prevent cross-site scripting (XSS) and buffer risks.
* **Network & API Security**: Deploys multi-tiered Rate Limiting via SlowAPI, strict Cross-Origin Resource Sharing (CORS), and sets stringent Security Headers (HSTS, CSP, XSS-Protection). 
* **Configuration Safety**: Sensitive data is securely managed through `.env` configurations; refer safely back to `.env.example`.

## 🛠️ Tech Stack

* **Languages**: Python, SQL
* **Frameworks**: FastAPI, Streamlit
* **Cheminformatics**: RDKit, Streamlit-Ketcher
* **Database**: PostgreSQL (with mcs07/postgres-rdkit)
* **Data Processing**: Pandas
* **Deployment**: Docker, Docker Compose

