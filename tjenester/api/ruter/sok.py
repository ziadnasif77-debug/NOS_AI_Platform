import logging
import os
import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
ruter = APIRouter(prefix="/sok", tags=["sok"])

SOK_URL = os.environ.get("SOK_URL", "http://sok:8003")


class SokForespoersel(BaseModel):
    """Validert kontrakt — hindrer ubundet `antall` (F4-3) og rå dict."""
    sporsmal: str = Field("", max_length=1000)
    filtre: dict = Field(default_factory=dict)
    antall: int = Field(10, ge=1, le=100)


@ruter.post("/")
async def sok(forespoersel: SokForespoersel):
    """
    Sok i arkivet.
    - sporsmal: Fritekst sokestreng pa norsk (maks 1000 tegn)
    - filtre: ytelse, fylke, fil_id
    - antall: Maks antall resultater (1-100, standard 10)
    """
    try:
        svar = requests.post(f"{SOK_URL}/sok", json=forespoersel.model_dump(), timeout=30)
    except Exception:
        logger.exception("Søketjeneste utilgjengelig")
        raise HTTPException(status_code=503, detail="Søketjeneste utilgjengelig")
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=svar.status_code, content=svar.json())
