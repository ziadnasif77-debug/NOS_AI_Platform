import sys
import re
from datetime import datetime
from typing import List

sys.path.insert(0, "/config")
from config.config_loader import CONFIG

if not CONFIG["lag"]["lag4_validering"]:
    raise SystemExit("Lag 4 (validering) er deaktivert i config.yaml")

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="NAV Lag 4 — Validering")

_PORT = CONFIG["porter"]["lag4"]

_OBLIGATORISKE_FELT = {
    "soknad": ["navn", "fodselsnummer", "dato"],
    "vedtak": ["navn", "fodselsnummer", "dato", "utfall"],
    "korrespondanse": ["navn", "dato"],
    "skjema": ["navn"],
}


class ValiderInn(BaseModel):
    fil_id: str
    dokumenttype: str
    felter: dict


def valider_fodselsnummer(fnr: str) -> bool:
    """Mod11-validering av norsk fødselsnummer (11 siffer)."""
    if not fnr or not fnr.isdigit() or len(fnr) != 11:
        return False
    vekter1 = [3, 7, 6, 1, 8, 9, 4, 5, 2]
    vekter2 = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]

    def kontrollsiffer(sifre, vekter):
        s = sum(int(sifre[i]) * vekter[i] for i in range(len(vekter)))
        r = 11 - (s % 11)
        return 0 if r == 11 else r

    k1 = kontrollsiffer(fnr, vekter1)
    k2 = kontrollsiffer(fnr, vekter2)
    return k1 == int(fnr[9]) and k2 == int(fnr[10])


def valider_dato(dato: str) -> bool:
    """Dato mellom 1900 og 2024."""
    if not dato:
        return False
    for fmt in ["%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]:
        try:
            d = datetime.strptime(dato.strip(), fmt)
            return 1900 <= d.year <= 2024
        except ValueError:
            continue
    return False


@app.post("/valider")
async def valider(data: ValiderInn):
    mangler: List[str] = []
    feil: List[str] = []
    advarsler: List[str] = []

    obligatoriske = _OBLIGATORISKE_FELT.get(data.dokumenttype, ["navn"])
    for felt in obligatoriske:
        if not data.felter.get(felt):
            mangler.append(felt)

    fnr = data.felter.get("fodselsnummer")
    if fnr and not valider_fodselsnummer(fnr):
        feil.append(f"Ugyldig fødselsnummer: {fnr}")

    dato = data.felter.get("dato")
    if dato and not valider_dato(dato):
        feil.append(f"Ugyldig eller utenfor rekkevidde dato: {dato}")

    konfidens = data.felter.get("konfidens", 1.0)
    if isinstance(konfidens, (int, float)) and konfidens < 0.7:
        advarsler.append(f"Lav konfidens: {konfidens:.0%}")

    gyldig = len(mangler) == 0 and len(feil) == 0
    return {"gyldig": gyldig, "mangler": mangler, "feil": feil, "advarsler": advarsler}


@app.get("/helse")
async def helse():
    return {"status": "ok", "lag": 4, "aktiv": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=_PORT)
