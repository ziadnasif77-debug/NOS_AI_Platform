FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir psycopg2-binary redis pyyaml prometheus-client kfp
COPY config /app/config
COPY delt /app/delt
COPY kubeflow /app/kubeflow
COPY tjenester/workers /app/tjenester/workers
CMD ["python", "-m", "tjenester.workers.reconciliation.reconciliation_worker"]
