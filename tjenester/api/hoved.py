import os
import sys
import json
import uvicorn
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

sys.path.insert(0, "/delt")
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
REDIS_URL = os.environ.get("REDIS_URL", "")

AAPNE_STIER = {"/helse", "/statistikk"}
AAPNE_PREFIKSER = ("/jobb/",)


@app.middleware("http")
async def api_nokkel_middleware(forespørsel: Request, neste):
    """Krev X-API-Key header. Unntak: /helse, /statistikk og /jobb/<id> (asynkron polling)."""
    if API_NOKKEL:
        sti = forespørsel.url.path
        aapen = sti in AAPNE_STIER or any(sti.startswith(p) for p in AAPNE_PREFIKSER)
        if not aapen:
            nokkel = forespørsel.headers.get("X-API-Key", "")
            if nokkel != API_NOKKEL:
                return JSONResponse(
                    {"feil": "Ugyldig eller manglende API-nøkkel"},
                    status_code=401
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


@app.get("/jobb/{jobb_id}")
async def sjekk_jobb(jobb_id: str):
    """
    Sjekk status for en asynkron behandlingsjobb.
    Statuser: i_ko → ocr_pagar → nlp_pagar / gjennomgang → fullfort / feil
    """
    if not REDIS_URL:
        raise HTTPException(status_code=503, detail="Jobbsporing ikke konfigurert (REDIS_URL mangler)")
    try:
        import redis
        r = redis.from_url(REDIS_URL, decode_responses=True)
        data = r.get(f"jobb:{jobb_id}")
        if not data:
            raise HTTPException(status_code=404, detail="Jobb ikke funnet (kan ha utløpt etter 24 timer)")
        return json.loads(data)
    except redis.RedisError as feil:
        raise HTTPException(status_code=503, detail=f"Redis utilgjengelig: {feil}")


@app.get("/dokument/{fil_id}")
async def hent_dokument(fil_id: str):
    try:
        svar = requests.post(
            f"{SOK_URL}/sok",
            json={"sporsmal": fil_id, "antall": 1},
            timeout=30
        )
        return svar.json()
    except Exception as feil:
        raise HTTPException(status_code=503, detail=str(feil))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
