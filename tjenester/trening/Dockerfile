# Bygges fra repo-rot: docker build -f tjenester/trening/Dockerfile .
# Trenings-image for Kubeflow-treningspipelinen (LayoutLMv3-finjustering).
FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir torch transformers pillow paddleocr pymupdf requests pyyaml

COPY config /app/config
COPY delt /app/delt
COPY skript /app/skript

ENV PYTHONPATH=/app

CMD ["python", "skript/finjuster.py"]
