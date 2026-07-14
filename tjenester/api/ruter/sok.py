import os
import requests
from fastapi import APIRouter, HTTPException

ruter = APIRouter(prefix="/sok", tags=["sok"])

SOK_URL = os.environ.get("SOK_URL", "http://sok:8003")


@ruter.post("/")
async def sok(data: dict):
    """
    Sok i arkivet.
    Parametere:
    - sporsmal: Fritekst sokestreng pa norsk
    - filtre: ytelse, fylke, fil_id
    - antall: Maks antall resultater (standard: 10)
    """
    try:
        svar = requests.post(f"{SOK_URL}/sok", json=data, timeout=30)
    except Exception as feil:
        raise HTTPException(status_code=503, detail=f"Soketjeneste utilgjengelig: {feil}")
    # Propager soketjenestens statuskode — 400 fra ugyldig filter skal
    # ikke bli 200 hos klienten.
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=svar.status_code, content=svar.json())
