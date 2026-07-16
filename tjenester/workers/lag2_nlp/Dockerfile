FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir psycopg2-binary redis pyyaml transformers pillow torch prometheus-client pydantic
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
# 4-bit-kvantisering (Borealis-4B må dele 8 GB GPU med de andre modellene)
RUN pip install --no-cache-dir bitsandbytes accelerate
COPY config /app/config
COPY delt /app/delt
COPY tjenester/workers /app/tjenester/workers
CMD ["python", "-m", "tjenester.workers.lag2_nlp.lag2"]
