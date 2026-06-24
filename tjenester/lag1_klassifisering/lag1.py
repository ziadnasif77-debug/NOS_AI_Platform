import sys

sys.path.insert(0, "/config")
from config.config_loader import CONFIG

if not CONFIG["lag"]["lag1_klassifisering"]:
    raise SystemExit("Lag 1 (klassifisering) er deaktivert i config.yaml")

import uvicorn
import cv2
import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="NAV Lag 1 — Dokumentklassifisering")

_PORT = CONFIG["porter"]["lag1"]

HANDSKRIFT = "handskrift"
TRYKT = "trykt"
TABELL = "tabell"
BLANDET = "blandet"


class BildeStiInn(BaseModel):
    bilde_sti: str


def _beregn_tabell_poeng(bilde: np.ndarray) -> float:
    kanter = cv2.Canny(bilde, 50, 150)
    linjer = cv2.HoughLinesP(
        kanter, 1, np.pi / 180,
        threshold=100, minLineLength=100, maxLineGap=10
    )
    if linjer is None:
        return 0.0
    vannrette = sum(1 for l in linjer if abs(l[0][1] - l[0][3]) < 5)
    loddrette = sum(1 for l in linjer if abs(l[0][0] - l[0][2]) < 5)
    return min(1.0, (vannrette + loddrette) / 50.0)


def _beregn_handskrift_poeng(bilde: np.ndarray) -> float:
    _, binaer = cv2.threshold(bilde, 128, 255, cv2.THRESH_BINARY_INV)
    konturer, _ = cv2.findContours(
        binaer, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not konturer:
        return 0.0
    gjennomsnitt_areal = np.mean([cv2.contourArea(k) for k in konturer])
    return min(1.0, gjennomsnitt_areal / 100.0)


def _beregn_trykt_poeng(bilde: np.ndarray) -> float:
    std = np.std(bilde)
    return min(1.0, std / 80.0)


def klassifiser_side(bilde_sti: str) -> tuple:
    """Klassifiser dokumenttype. Returnerer (type, konfidens)."""
    bilde = cv2.imread(bilde_sti, cv2.IMREAD_GRAYSCALE)
    if bilde is None:
        return BLANDET, 0.5
    tabell_poeng = _beregn_tabell_poeng(bilde)
    if tabell_poeng > 0.3:
        return TABELL, tabell_poeng
    handskrift_poeng = _beregn_handskrift_poeng(bilde)
    trykt_poeng = _beregn_trykt_poeng(bilde)
    if handskrift_poeng > 0.7:
        return HANDSKRIFT, handskrift_poeng
    elif trykt_poeng > 0.7:
        return TRYKT, trykt_poeng
    else:
        return BLANDET, max(handskrift_poeng, trykt_poeng, 0.5)


@app.post("/klassifiser")
async def klassifiser(data: BildeStiInn):
    dokumenttype, konfidens = klassifiser_side(data.bilde_sti)
    return {"type": dokumenttype, "konfidens": konfidens}


@app.get("/helse")
async def helse():
    return {"status": "ok", "lag": 1, "aktiv": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=_PORT)
