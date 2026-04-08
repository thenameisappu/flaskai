FROM --platform=linux/amd64 python:3.11-slim

# We explicitly use linux/amd64 to prevent "exec format error" across environments

RUN apt-get update && apt-get install -y \
    libxrender1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*
    
WORKDIR /app

# Copy requirements and install via pip with no-cache for lightweight build
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

EXPOSE 8000

CMD uvicorn api:app --host 0.0.0.0 --port 8000
