import os
import sys
import uvicorn
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tjenester/api")
from delt.verktøy import konfigurer_logging

logger = konfigurer_logging("api-tjeneste")
app = FastAPI(title="NAV Archive API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

API_NOKKEL = os.environ.get("API_NOKKEL", "")
if not API_NOKKEL:
    logger.warning(
        "API_NOKKEL ikke satt — alle endepunkter er ubeskyttede. "
        "Sett miljøvariabelen API_NOKKEL i produksjon."
    )

AAPNE_STIER = {"/helse"}


@app.middleware("http")
async def api_nokkel_middleware(forespørsel: Request, neste):
    """Krev X-API-Key header på alle endepunkter unntatt /helse."""
    if API_NOKKEL:
        sti = forespørsel.url.path
        if sti not in AAPNE_STIER:
            nokkel = forespørsel.headers.get("X-API-Key", "")
            if nokkel != API_NOKKEL:
                return JSONResponse(
                    {"feil": "Ugyldig eller manglende API-nøkkel"},
                    status_code=401,
                )
    return await neste(forespørsel)

from ruter.sok import ruter as sok_ruter
from ruter.last_opp import ruter as last_opp_ruter
from ruter.gjennomgang import ruter as gjennomgang_ruter

app.include_router(sok_ruter)
app.include_router(last_opp_ruter)
app.include_router(gjennomgang_ruter)

SOK_URL = os.environ.get("SOK_URL", "http://sok:8003")
OCR_URL = os.environ.get("OCR_URL", "http://ocr:8001")
NLP_URL = os.environ.get("NLP_URL", "http://nlp:8002")
LABEL_STUDIO_URL = os.environ.get("GJENNOMGANG_URL", "http://label-studio:8080")


@app.get("/helse")
async def helse():
    tjenester = {}
    for navn, url in [
        ("ocr", f"{OCR_URL}/helse"),
        ("nlp", f"{NLP_URL}/helse"),
        ("sok", f"{SOK_URL}/helse"),
        ("label-studio", f"{LABEL_STUDIO_URL}/health"),
    ]:
        try:
            svar = requests.get(url, timeout=5)
            tjenester[navn] = svar.json().get("status", "ok")
        except Exception:
            tjenester[navn] = "ikke tilgjengelig"
    return {"status": "ok", "tjeneste": "api", "avhengigheter": tjenester}


@app.get("/statistikk")
async def statistikk():
    try:
        svar = requests.get(f"{SOK_URL}/statistikk", timeout=10)
        return svar.json()
    except Exception as feil:
        raise HTTPException(status_code=503, detail=f"Soketjeneste utilgjengelig: {feil}")



@app.get("/dokument/{job_id}")
async def hent_dokument(job_id: str):
    try:
        svar = requests.post(
            f"{SOK_URL}/sok",
            json={"filtre": {"fil_id": job_id}, "antall": 1},
            timeout=30,
        )
        resultat = svar.json()
        if not resultat.get("resultater"):
            raise HTTPException(status_code=404, detail="Dokument ikke funnet")
        return resultat
    except HTTPException:
        raise
    except Exception as feil:
        raise HTTPException(status_code=503, detail=str(feil))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
