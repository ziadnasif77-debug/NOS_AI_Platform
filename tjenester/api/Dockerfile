# Bygges fra repo-rot: docker build -f tjenester/api/Dockerfile .
# API-et trenger config/ og delt/ i tillegg til egen kode,
# samt kompilert Kubeflow-pipeline for kubeflow-modus.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY tjenester/api/krav.txt .
RUN pip install --no-cache-dir -r krav.txt

COPY config /app/config
COPY delt /app/delt
COPY skript /app/skript
COPY kubeflow /app/kubeflow
COPY tjenester/api /app/tjenester/api

CMD ["python", "tjenester/api/hoved.py"]
