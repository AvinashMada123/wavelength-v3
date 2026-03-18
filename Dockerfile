FROM python:3.12-slim

WORKDIR /app

# System deps for onnxruntime (smart turn, VAD) and audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

COPY . .

# Cloud Run uses PORT env var
ENV PORT=8080
EXPOSE 8080

# Single worker — Pipecat pipelines are async and share one event loop.
# Multiple workers cause issues with torch/onnxruntime cold load times
# (gunicorn kills workers that take >30s to start).
# Single worker handles 100+ concurrent WebSocket connections fine since
# all heavy compute (LLM, TTS, STT) is offloaded to external APIs.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--timeout-keep-alive", "120"]
