import os
import requests
from fastapi import APIRouter, HTTPException

ruter = APIRouter(prefix="/gjennomgang", tags=["gjennomgang"])

GJENNOMGANG_URL = os.environ.get("GJENNOMGANG_URL", "http://gjennomgang:8004")


@ruter.get("/ko")
async def hent_ko():
    """Henter gjennomgangskoen."""
    try:
        svar = requests.get(f"{GJENNOMGANG_URL}/ko", timeout=10)
        return svar.json()
    except Exception as feil:
        raise HTTPException(status_code=503, detail=str(feil))


@ruter.post("/korriger/{fil_id}")
async def korriger(fil_id: str, data: dict):
    """Sender en korreksjon til gjennomgangstjenesten."""
    try:
        svar = requests.post(
            f"{GJENNOMGANG_URL}/korriger/{fil_id}",
            json=data,
            timeout=30
        )
        return svar.json()
    except Exception as feil:
        raise HTTPException(status_code=503, detail=str(feil))
