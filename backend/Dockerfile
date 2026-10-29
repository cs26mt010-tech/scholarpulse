FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for MySQL client and healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-mysql-client \
    gcc \
    libmariadb-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY data /app/data
COPY docs /app/docs
COPY scripts /app/scripts
COPY frontend /app/frontend

RUN mkdir -p /app/uploads && chmod +x /app/backend/entrypoint.sh

ENV PYTHONPATH=/app/backend:/app

EXPOSE 8000

ENTRYPOINT ["bash", "/app/backend/entrypoint.sh"]
