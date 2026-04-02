FROM mcs07/postgres-rdkit:latest AS base

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    libxrender1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
EXPOSE 8501

CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port 8000 & streamlit run App.py --server.port 8501 --server.address 0.0.0.0"]
