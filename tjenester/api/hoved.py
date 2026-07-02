import os
import sys
import time
import uvicorn
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tjenester/api")
from delt.verktøy import konfigurer_logging
from delt.autentisering import sjekk_forespoersel, auth_modus
from delt import metrikker

logger = konfigurer_logging("api-tjeneste")
app = FastAPI(title="NAV Archive API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

API_NOKKEL = os.environ.get("API_NOKKEL", "")
if auth_modus() == "api_nokkel" and not API_NOKKEL:
    logger.warning(
        "API_NOKKEL ikke satt — alle endepunkter er ubeskyttede. "
        "Sett miljøvariabelen API_NOKKEL i produksjon, "
        "eller bruk AUTH_MODUS=oidc for token-basert autentisering."
    )

AAPNE_STIER = {"/helse", "/metrics"}


@app.middleware("http")
async def api_nokkel_middleware(forespørsel: Request, neste):
    """
    Autentisering på alle endepunkter unntatt /helse og /metrics.
    AUTH_MODUS=api_nokkel: X-API-Key header (konstant-tid-sammenligning).
    AUTH_MODUS=oidc:       Bearer-token validert mot OIDC-utsteder.
    """
    sti = forespørsel.url.path
    if sti not in AAPNE_STIER:
        feil = sjekk_forespoersel(forespørsel.headers, API_NOKKEL)
        if feil:
            return JSONResponse({"feil": feil}, status_code=401)
    return await neste(forespørsel)


@app.middleware("http")
async def metrikk_middleware(forespørsel: Request, neste):
    """Teller forespørsler og måler latens per rute (lav kardinalitet)."""
    start = time.monotonic()
    svar = await neste(forespørsel)
    rute = forespørsel.scope.get("route")
    rutemal = getattr(rute, "path", "ukjent")
    metrikker.tell_api(forespørsel.method, rutemal, svar.status_code)
    metrikker.observer_api_latens(rutemal, time.monotonic() - start)
    return svar


@app.get("/metrics")
async def metrics():
    payload, content_type = metrikker.metrikk_tekst()
    return Response(content=payload, media_type=content_type)

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
