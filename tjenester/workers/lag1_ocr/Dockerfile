FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir psycopg2-binary redis pyyaml "paddleocr<3.0.0" transformers pillow torch prometheus-client "marker-pdf<1.0.0"
# PaddleOCR er kun API-laget — selve inferens-rammeverket må med:
RUN pip install --no-cache-dir paddlepaddle
COPY config /app/config
COPY delt /app/delt
COPY tjenester/workers /app/tjenester/workers
CMD ["python", "-m", "tjenester.workers.lag1_ocr.lag1"]
