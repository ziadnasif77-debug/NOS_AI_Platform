#!/bin/bash
# Overforer hele prosjektet til ny server med en kommando.
# Bruk: bash skript/migrer_server.sh bruker@server-adresse

SERVER=$1
if [ -z "$SERVER" ]; then
    echo "Bruk: bash skript/migrer_server.sh bruker@server-adresse"
    exit 1
fi

echo "Overforer nav-arkiv til $SERVER..."
rsync -avz --exclude='data/inntak/*' \
            --exclude='data/behandlet/*' \
            --exclude='data/logger/*' \
            --exclude='__pycache__' \
            --exclude='.env' \
    ./ $SERVER:~/nav-arkiv/

echo "Overforer .env manuelt og kjor: make last-ned-modeller && make start"
