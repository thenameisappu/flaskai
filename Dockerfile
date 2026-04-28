FROM python:3.11-slim AS builder

WORKDIR /app

COPY requirements.txt .

# Install system deps required by rdkit and psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libboost-all-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /venv \
    && /venv/bin/pip install --upgrade pip \
    && /venv/bin/pip install --no-cache-dir -r requirements.txt


FROM python:3.11-slim AS runtime

WORKDIR /app

# Runtime libs needed by rdkit and psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libboost-serialization1.74.0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /venv /venv

COPY . .

ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-4} --log-level ${LOG_LEVEL:-info}"]