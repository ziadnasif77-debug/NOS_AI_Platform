# Samme major-versjon som postgres-tjenesten — pg_dump/pg_restore må
# aldri være eldre enn serveren de dumper fra.
FROM postgres:16-alpine

RUN apk add --no-cache python3

WORKDIR /app
COPY skript/sikkerhetskopi.py .

# Overstyr postgres-imagets entrypoint — dette er en klient, ikke en server
ENTRYPOINT []
CMD ["python3", "/app/sikkerhetskopi.py", "--daemon"]
