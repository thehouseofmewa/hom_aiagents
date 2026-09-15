# HOM Voice Bot Backend - Dockerfile
# Builds the Pipecat-based voice agent backend.
#
# Build:
#   docker build -f Dockerfile -t hom-backend .
# Run:
#   docker run -p 8080:8080 hom-backend

FROM python:3.12-slim AS base

# Prevents Python from writing .pyc files and buffering output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System dependencies needed by Pipecat (audio + codecs + build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ffmpeg \
    libasound2 \
    libportaudio2 \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency manifests first for better layer caching
COPY requirements.in requirements.in
COPY requirements.txt requirements.txt

# Install Python dependencies (fall back to requirements.in if no compiled lock file)
RUN pip install --upgrade pip && \
    if [ -f requirements.txt ]; then \
        pip install -r requirements.txt; \
    else \
        pip install -r requirements.in; \
    fi

# Copy the application source
COPY . .

# Expose the Pipecat / FastAPI server port
EXPOSE 8080

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Default command: run the FastAPI app. Override to run a specific pipeline.
CMD ["uvicorn", "api.v1.main:app", "--host", "0.0.0.0", "--port", "8080"]