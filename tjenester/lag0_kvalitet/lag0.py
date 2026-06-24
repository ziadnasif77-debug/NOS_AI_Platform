import sys
from pathlib import Path

sys.path.insert(0, "/config")
from config.config_loader import CONFIG

if not CONFIG["lag"]["lag0_kvalitet"]:
    raise SystemExit("Lag 0 (kvalitet) er deaktivert i config.yaml")

import uvicorn
import cv2
import fitz  # PyMuPDF
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="NAV Lag 0 — Bildekvalitet")

_PORT = CONFIG["porter"]["lag0"]
_TERSKEL = CONFIG["terskler"]["bildekvalitet"]
_TMP = CONFIG["stier"]["tmp"]


class BildeStiInn(BaseModel):
    bilde_sti: str


class FilInn(BaseModel):
    bilde_sti: str
    fil_id: str


class PdfInn(BaseModel):
    pdf_sti: str
    fil_id: str


def maal_bildekvalitet(bilde_sti: str) -> float:
    """Beregn score 0.0-1.0 basert på kontrast (Laplacian variance / 1000, capped at 1.0)."""
    bilde = cv2.imread(bilde_sti)
    if bilde is None:
        return 0.0
    grat = cv2.cvtColor(bilde, cv2.COLOR_BGR2GRAY)
    lap_var = cv2.Laplacian(grat, cv2.CV_64F).var()
    return min(lap_var / 1000.0, 1.0)


def forbehandle_bilde(raa_sti: str, utgang_sti: str) -> str:
    """OpenCV: deskew + CLAHE + Otsu binarisering."""
    bilde = cv2.imread(raa_sti)
    if bilde is None:
        raise ValueError(f"Kunne ikke lese bilde: {raa_sti}")
    grat = cv2.cvtColor(bilde, cv2.COLOR_BGR2GRAY)
    renset = cv2.fastNlMeansDenoising(grat, h=10)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    forbedret = clahe.apply(renset)
    _, binaer = cv2.threshold(
        forbedret, 0, 255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    cv2.imwrite(utgang_sti, binaer)
    return utgang_sti


def pdf_til_bilde(pdf_sti: str, utgang_sti: str) -> str:
    """Konverterer første side i PDF til PNG via PyMuPDF."""
    dok = fitz.open(pdf_sti)
    side = dok[0]
    pix = side.get_pixmap(matrix=fitz.Matrix(2, 2))
    pix.save(utgang_sti)
    dok.close()
    return utgang_sti


@app.post("/sjekk-kvalitet")
async def sjekk_kvalitet(data: BildeStiInn):
    score = maal_bildekvalitet(data.bilde_sti)
    godkjent = score >= _TERSKEL
    grunn = "ok" if godkjent else f"score {score:.2f} under terskel {_TERSKEL}"
    return {"godkjent": godkjent, "score": score, "grunn": grunn}


@app.post("/forbehandle")
async def forbehandle(data: FilInn):
    utgang_sti = f"{_TMP}/{data.fil_id}_forbehandlet.png"
    forbehandle_bilde(data.bilde_sti, utgang_sti)
    return {"forbehandlet_sti": utgang_sti}


@app.post("/pdf-til-bilde")
async def konverter_pdf(data: PdfInn):
    utgang_sti = f"{_TMP}/{data.fil_id}_side0.png"
    pdf_til_bilde(data.pdf_sti, utgang_sti)
    return {"bilde_sti": utgang_sti}


@app.get("/helse")
async def helse():
    return {"status": "ok", "lag": 0, "aktiv": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=_PORT)
