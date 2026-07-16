FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY krav.txt .
RUN pip install --no-cache-dir -r krav.txt

COPY . .

CMD ["python", "hoved.py"]
