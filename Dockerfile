# DocBlendAI server image (CPU only).
#
#   docker build -t docblendai .
#   docker run -p 8000:8000 -e GEMINI_API_KEY=... -v docblendai-data:/data docblendai
#
# The default handwriting engine (PaddleOCR models via RapidOCR/ONNX Runtime) is
# included. The optional TrOCR engine needs PyTorch (~1 GB more); add it with
#   docker build --build-arg WITH_TROCR=true -t docblendai .
FROM python:3.11-slim-bookworm

ARG WITH_TROCR=false

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Tesseract for printed scans; libgl/glib for OpenCV (used by RapidOCR).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies before copying the code so code changes reuse this layer.
# Test/evaluation tools are left out; TrOCR's stack only with WITH_TROCR=true
# (CPU wheels of torch, much smaller than the default CUDA build on Linux).
COPY requirements.txt .
RUN grep -vE '^(torch|torchvision|transformers|huggingface_hub|sentencepiece|jiwer|pytest|httpx2)==' requirements.txt > requirements-docker.txt \
    && if [ "$WITH_TROCR" = "true" ]; then \
         pip install --index-url https://download.pytorch.org/whl/cpu \
           "$(grep -E '^torch==' requirements.txt | cut -d' ' -f1)" \
           "$(grep -E '^torchvision==' requirements.txt | cut -d' ' -f1)" \
         && grep -E '^(transformers|huggingface_hub|sentencepiece)==' requirements.txt | cut -d' ' -f1 >> requirements-docker.txt; \
       fi \
    && pip install -r requirements-docker.txt

COPY app ./app
COPY data/calibration.json ./data/calibration.json

# Runtime data (database, vectors, uploads) lives in /data: mount a volume there
# so documents survive container restarts. Calibration stays in the image.
ENV DATABASE_URL=sqlite:////data/docblendai.db \
    CHROMA_DIR=/data/chroma_db \
    UPLOAD_DIR=/data/uploads \
    HF_HOME=/data/hf_cache \
    PORT=8000

# Run as an unprivileged user (uid 1000, which Hugging Face Spaces also expects).
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data \
    && chown -R app:app /data
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health')"

# One worker: SQLite, ChromaDB, and the OCR models are per-process.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
