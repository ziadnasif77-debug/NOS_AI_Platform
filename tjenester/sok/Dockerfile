# Bygges fra repo-rot: docker build -f tjenester/sok/Dockerfile .
# Søketjenesten importerer delt/ — må derfor bygges fra rot.
FROM python:3.11-slim

WORKDIR /app

COPY tjenester/sok/krav.txt .
RUN pip install --no-cache-dir -r krav.txt

COPY delt /app/delt
COPY tjenester/sok /app

CMD ["python", "hoved.py"]
