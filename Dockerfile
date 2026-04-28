FROM --platform=linux/amd64 python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir --prefer-binary --timeout 300 --retries 5 -r requirements.txt

COPY . .

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${API_PORT:-8000} --workers ${UVICORN_WORKERS:-4} --log-level ${LOG_LEVEL:-info}"]