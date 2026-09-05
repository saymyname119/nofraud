# ── Multi-stage Docker build for FraudSpike ──────────────────────────

# Stage 1: Build the React Dashboard
FROM node:20-alpine AS frontend-builder
WORKDIR /app/dashboard
COPY dashboard/package*.json ./
RUN npm install
COPY dashboard/ ./
RUN npm run build

# Stage 2: Python Backend & Final Runtime
FROM python:3.11-slim
WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application code
COPY app/ ./app
COPY config.yaml .
COPY ml/ ./ml
COPY scripts/ ./scripts

# Copy compiled frontend build from Stage 1
COPY --from=frontend-builder /app/dashboard/dist ./dashboard/dist

# Environment defaults
ENV PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    LOG_LEVEL=INFO \
    PORT=8000

EXPOSE 8000

# Run FastAPI server via Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
