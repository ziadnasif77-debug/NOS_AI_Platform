FROM python:3.11-slim
RUN pip install --no-cache-dir psycopg2-binary requests
WORKDIR /app
COPY skript/oppbevaring.py .
CMD ["python", "/app/oppbevaring.py", "--daemon"]
