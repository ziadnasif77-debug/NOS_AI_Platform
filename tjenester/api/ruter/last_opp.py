import os
import json
import uuid
import shutil
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException

ruter = APIRouter(prefix="/last-opp", tags=["opplasting"])

INNTAK_STI = os.environ.get("INNTAK_STI", "/data/inntak")
REDIS_URL = os.environ.get("REDIS_URL", "")


def _opprett_jobb_redis(jobb_id: str, filnavn: str) -> None:
    """Skriver initial jobbstatus til Redis. Stille ved feil (Redis kan være nede ved oppstart)."""
    if not REDIS_URL:
        return
    try:
        import redis
        r = redis.from_url(REDIS_URL, decode_responses=True)
        data = {"jobb_id": jobb_id, "status": "i_ko", "filnavn": filnavn}
        r.setex(f"jobb:{jobb_id}", 86400, json.dumps(data))
    except Exception:
        pass


@ruter.post("/")
async def last_opp(fil: UploadFile = File(...)):
    """
    Laster opp en PDF-fil til behandlingskøen.
    Returnerer umiddelbart med jobb_id — behandling skjer asynkront.
    Poll /jobb/{jobb_id} for status.
    """
    if not fil.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Kun PDF-filer er støttet")
    try:
        jobb_id = uuid.uuid4().hex[:12]
        utgang = Path(INNTAK_STI) / fil.filename
        utgang.parent.mkdir(parents=True, exist_ok=True)

        with open(utgang, "wb") as f:
            shutil.copyfileobj(fil.file, f)

        # Sidecar-fil: kobler jobb_id til filnavn for OCR-tjenestens jobbsporing
        sidecar = utgang.with_suffix(".jobb.json")
        with open(sidecar, "w", encoding="utf-8") as f:
            json.dump({"jobb_id": jobb_id, "filnavn": fil.filename}, f)

        _opprett_jobb_redis(jobb_id, fil.filename)

        return {
            "jobb_id": jobb_id,
            "filnavn": fil.filename,
            "status": "i_ko",
            "sjekk_status": f"/jobb/{jobb_id}",
        }
    except Exception as feil:
        raise HTTPException(status_code=500, detail=str(feil))
