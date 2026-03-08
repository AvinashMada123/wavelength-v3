FROM python:3.12-slim

WORKDIR /app

# System deps for onnxruntime (smart turn, VAD) and audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Copy credentials into image (gitignored, lives on server only)
COPY credentials/ /credentials/

# Cloud Run uses PORT env var
ENV PORT=8080
EXPOSE 8080

# Single worker — all concurrency is async within one event loop.
# Cloud Run scales instances horizontally.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
