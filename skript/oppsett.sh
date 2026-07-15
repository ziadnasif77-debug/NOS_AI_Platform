#!/usr/bin/env bash
# Ett-kommando lokalt oppsett: gjør alt som KAN gjøres uten å laste ned
# GB-vis med modeller eller kreve ekte GPU-maskinvare. Kjøres på
# UTVIKLERENS maskin (ikke i et sandkasse/CI-miljø) — GPU-sjekken tester
# den faktiske maskinvaren du kjører på.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "═══ 1/4 — .env ═══"
if [ ! -f .env ]; then
    cp .env.example .env
    echo "✓ .env opprettet fra .env.example"
else
    echo "✓ .env finnes allerede"
fi
if ! grep -q "^API_NOKKEL=.\+" .env; then
    echo "API_NOKKEL=nav-secret-2026" >> .env
    echo "✓ API_NOKKEL lagt til (bytt ut i produksjon)"
fi

echo
echo "═══ 2/4 — Datamapper ═══"
mkdir -p data/inntak data/behandlet data/gjennomgang data/finjustering data/logger
echo "✓ data/{inntak,behandlet,gjennomgang,finjustering,logger} klare"

echo
echo "═══ 3/4 — GPU-sjekk (kan IKKE gjøres i skyen — tester din maskin) ═══"
if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "✗ nvidia-smi ikke funnet — ingen NVIDIA-driver installert."
    echo "  Systemet kjører på CPU (fungerer, men Borealis-4B blir tregt/urealistisk)."
elif ! nvidia-smi >/dev/null 2>&1; then
    echo "✗ nvidia-smi finnes men feiler — sjekk NVIDIA-driveren."
else
    echo "✓ NVIDIA-driver funnet:"
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | sed 's/^/    /'
    if command -v docker >/dev/null 2>&1; then
        if docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi >/dev/null 2>&1; then
            echo "✓ Docker ser GPU-en (NVIDIA Container Toolkit er riktig satt opp)"
        else
            echo "✗ Docker ser IKKE GPU-en — NVIDIA Container Toolkit mangler eller er feil konfigurert."
            echo "  Installer: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"
            echo "  Uten dette kjører alle containere på CPU selv om GPU_ENHET=cuda:0 i .env."
        fi
    fi
fi

echo
echo "═══ 4/4 — AI-modeller (~17 GB — IKKE lastet ned automatisk her) ═══"
if [ -d modeller ] && [ -n "$(find modeller -maxdepth 2 -type f -size +1M 2>/dev/null | head -1)" ]; then
    echo "✓ modeller/ inneholder allerede filer — hopper over"
else
    echo "✗ modeller/ er tom eller mangler."
    echo "  Kjør nå (eller senere, tar tid — ~17 GB nedlasting, kan gjenopptas hvis avbrutt):"
    echo "    make last-ned-modeller"
fi

echo
echo "═══ Oppsett fullført ═══"
echo "Neste steg:"
echo "  make last-ned-modeller   # (hvis ikke gjort) — kan kjøres i bakgrunnen"
echo "  make start               # start alle tjenester"
echo "  make init-db             # opprett databaseskjema (første gang)"
echo "  make helse               # bekreft at alt kjører"
