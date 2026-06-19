import os
import requests
from fastapi import APIRouter, HTTPException

ruter = APIRouter(prefix="/gjennomgang", tags=["gjennomgang"])

GJENNOMGANG_URL = os.environ.get("GJENNOMGANG_URL", "http://label-studio:8080")
LABEL_STUDIO_API_KEY = os.environ.get("LABEL_STUDIO_API_KEY", "")


def _ls_headers() -> dict:
    return {"Authorization": f"Token {LABEL_STUDIO_API_KEY}"}


@ruter.get("/ko")
async def hent_ko():
    """Henter gjennomgangskøen fra Label Studio."""
    try:
        svar = requests.get(
            f"{GJENNOMGANG_URL}/api/projects/",
            headers=_ls_headers(),
            timeout=10
        )
        svar.raise_for_status()
        data = svar.json()
        antall = sum(p.get("task_number", 0) for p in data.get("results", []))
        return {
            "antall_venter": antall,
            "label_studio_url": os.environ.get("LABEL_STUDIO_URL", "http://localhost:8080"),
        }
    except Exception as feil:
        raise HTTPException(status_code=503, detail=str(feil))


@ruter.post("/korriger/{fil_id}")
async def korriger(fil_id: str, data: dict):
    """Sender en manuell korreksjon direkte til Label Studio."""
    try:
        prosjekt_id = os.environ.get("LABEL_STUDIO_OCR_PROSJEKT_ID", "1")
        svar = requests.post(
            f"{GJENNOMGANG_URL}/api/projects/{prosjekt_id}/import",
            headers=_ls_headers(),
            json=[{"fil_id": fil_id, **data}],
            timeout=30
        )
        svar.raise_for_status()
        return svar.json()
    except Exception as feil:
        raise HTTPException(status_code=503, detail=str(feil))
