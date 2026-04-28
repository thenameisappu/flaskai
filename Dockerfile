FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN python -m venv /venv \
    && /venv/bin/pip install --upgrade pip \
    && /venv/bin/pip install --no-cache-dir -r requirements.txt


FROM python:3.11-slim AS runtime

RUN echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/80retries && \
    apt-get update && apt-get install -y --no-install-recommends \
    libxrender1 \
    libxext6 \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1001 appgroup \
    && useradd  --uid 1001 --gid appgroup --no-create-home appuser

WORKDIR /app

COPY --from=builder /venv /venv

COPY --chown=appuser:appgroup . .

ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8000

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000", \
    "--workers", "4", "--log-level", "info"]