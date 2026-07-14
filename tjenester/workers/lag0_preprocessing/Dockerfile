FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir psycopg2-binary redis pyyaml opencv-python-headless numpy prometheus-client pymupdf
COPY config /app/config
COPY delt /app/delt
COPY tjenester/workers /app/tjenester/workers
CMD ["python", "-m", "tjenester.workers.lag0_preprocessing.lag0"]
