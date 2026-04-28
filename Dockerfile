FROM --platform=linux/amd64 continuumio/miniconda3:latest AS builder

WORKDIR /app

COPY requirements.txt .

RUN conda install -y -c conda-forge \
    rdkit \
    psycopg2 \
    && conda clean -afy

RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    python-dotenv \
    pydantic \
    slowapi \
    limits \
    pandas


FROM --platform=linux/amd64 continuumio/miniconda3:latest AS runtime

WORKDIR /app

COPY --from=builder /opt/conda /opt/conda
COPY . .

ENV PATH="/opt/conda/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-4} --log-level ${LOG_LEVEL:-info}"]