import os
import sys
import uvicorn
from fastapi import FastAPI, HTTPException
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/delt")
from delt.verktøy import konfigurer_logging, lagre_json, les_json

logger = konfigurer_logging("gjennomgang-tjeneste")
app = FastAPI(title="NAV Gjennomgangstjeneste")

GJENNOMGANG_STI = os.environ.get("GJENNOMGANG_STI", "/data/gjennomgang")
FINJUSTERING_STI = os.environ.get("FINJUSTERING_STI", "/data/finjustering")
MIN_KORREKSJONER = int(os.environ.get("MIN_KORREKSJONER_FOR_FINJUSTERING", "500"))


@app.get("/ko")
async def hent_ko():
    """Returnerer liste over dokumenter som venter pa gjennomgang."""
    try:
        filer = list(Path(GJENNOMGANG_STI).glob("*.json"))
        return {
            "antall_venter": len(filer),
            "dokumenter": [f.stem for f in filer[:20]]
        }
    except Exception as feil:
        raise HTTPException(status_code=500, detail=str(feil))


@app.post("/legg-til-ko/{fil_id}")
async def legg_til_ko(fil_id: str, data: dict):
    """Legger et dokument til gjennomgangskoen."""
    try:
        utgang = f"{GJENNOMGANG_STI}/{fil_id}.json"
        lagre_json(data, utgang)
        return {"status": "lagt til", "fil_id": fil_id}
    except Exception as feil:
        raise HTTPException(status_code=500, detail=str(feil))


@app.post("/korriger/{fil_id}")
async def korriger(fil_id: str, data: dict):
    """Lagrer en korreksjon fra saksbehandleren."""
    try:
        korreksjon = {
            "fil_id": fil_id,
            "original_tekst": data.get("original_tekst"),
            "korrekt_tekst": data.get("korrekt_tekst"),
            "korrigerte_felt": data.get("felt", {}),
            "tidsstempel": datetime.now().isoformat(),
            "saksbehandler": data.get("saksbehandler", "ukjent"),
        }
        utgang = f"{FINJUSTERING_STI}/{fil_id}_korreksjon.json"
        lagre_json(korreksjon, utgang)
        antall = len(list(Path(FINJUSTERING_STI).glob("*.json")))
        logger.info(f"Korreksjon lagret. Totalt: {antall}/{MIN_KORREKSJONER}")
        gjennomgang_fil = Path(f"{GJENNOMGANG_STI}/{fil_id}.json")
        if gjennomgang_fil.exists():
            gjennomgang_fil.unlink()
        return {"status": "lagret", "antall_korreksjoner": antall}
    except Exception as feil:
        raise HTTPException(status_code=500, detail=str(feil))


@app.get("/helse")
async def helse():
    antall_venter = len(list(Path(GJENNOMGANG_STI).glob("*.json")))
    antall_korreksjoner = len(list(Path(FINJUSTERING_STI).glob("*.json")))
    return {
        "status": "ok",
        "venter_gjennomgang": antall_venter,
        "totalt_korreksjoner": antall_korreksjoner,
        "terskel": MIN_KORREKSJONER
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8004)
