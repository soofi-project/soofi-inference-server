FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "torch" "torchvision" --index-url https://download.pytorch.org/whl/cu124 \
    && pip install --no-cache-dir \
    "fastapi[standard]>=0.115,<2" \
    "uvicorn[standard]>=0.30,<1" \
    "docling>=2.74,<3" \
    "python-multipart>=0.0.18,<1"

RUN useradd --create-home appuser
USER appuser

ENV HF_HUB_OFFLINE=1
ENV DOCLING_ARTIFACTS_PATH=/home/appuser/.cache/docling/models

WORKDIR /app
COPY app.py /app/app.py

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=60s \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
