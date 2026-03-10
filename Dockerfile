FROM python:3.12-slim

WORKDIR /app

# System deps for onnxruntime (smart turn, VAD) and audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run uses PORT env var
ENV PORT=8080
EXPOSE 8080

# 4 workers across 8 CPUs — distributes concurrent calls across separate event loops.
# Each WebSocket connection stays on the worker that accepted it.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "4"]
