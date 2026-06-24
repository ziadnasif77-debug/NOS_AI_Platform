FROM python:3.11-slim
WORKDIR /app
COPY krav.txt .
RUN pip install --no-cache-dir -r krav.txt
COPY . .
CMD ["python", "helsesjekk.py"]
