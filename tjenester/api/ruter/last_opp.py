import os
import shutil
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException

ruter = APIRouter(prefix="/last-opp", tags=["opplasting"])

INNTAK_STI = os.environ.get("INNTAK_STI", "/data/inntak")


@ruter.post("/")
async def last_opp(fil: UploadFile = File(...)):
    """Laster opp en PDF-fil manuelt til behandlingskoen."""
    if not fil.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Kun PDF-filer er stottet")
    try:
        utgang = Path(INNTAK_STI) / fil.filename
        utgang.parent.mkdir(parents=True, exist_ok=True)
        with open(utgang, "wb") as f:
            shutil.copyfileobj(fil.file, f)
        return {"status": "mottatt", "filnavn": fil.filename}
    except Exception as feil:
        raise HTTPException(status_code=500, detail=str(feil))
