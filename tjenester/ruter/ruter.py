import sys
from typing import Optional

sys.path.insert(0, "/config")
from config.config_loader import CONFIG

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="NAV Ruter")

_PORT = CONFIG["porter"]["ruter"]
TERSKEL_OCR = CONFIG["terskler"]["ocr_konfidens"] / 100
TERSKEL_NLP = CONFIG["terskler"]["nlp_konfidens"] / 100


class RuterInn(BaseModel):
    fil_id: str
    lag0: Optional[dict] = None
    lag1: Optional[dict] = None
    lag2: Optional[dict] = None
    lag3: Optional[dict] = None
    lag4: Optional[dict] = None


def bestem_vei(lag0_svar, lag1_svar, lag2_svar, lag3_svar, lag4_svar) -> tuple:
    """Returnerer ("sok" | "label_studio", grunn, prosjekt_id | None)"""
    ls_prosjekter = CONFIG["label_studio"]["prosjekter"]

    if lag0_svar and not lag0_svar.get("godkjent", True):
        return ("label_studio", "daarlig_bildekvalitet", ls_prosjekter["lag0"])

    if lag2_svar:
        konfidens = lag2_svar.get("konfidens", 1.0)
        if konfidens < TERSKEL_OCR:
            return ("label_studio", "lav_ocr_konfidens", ls_prosjekter["lag2"])

    if lag3_svar:
        konfidens = lag3_svar.get("konfidens", 1.0)
        if konfidens < TERSKEL_NLP:
            return ("label_studio", "usikker_nlp", ls_prosjekter["lag3"])

    if lag4_svar and not lag4_svar.get("gyldig", True):
        return ("label_studio", "valideringsfeil", ls_prosjekter["lag4"])

    return ("sok", "alle_lag_godkjent", None)


@app.post("/ruter")
async def ruter_endepunkt(data: RuterInn):
    destinasjon, grunn, prosjekt_id = bestem_vei(
        data.lag0, data.lag1, data.lag2, data.lag3, data.lag4
    )
    return {"destinasjon": destinasjon, "prosjekt_id": prosjekt_id, "grunn": grunn}


@app.get("/helse")
async def helse():
    return {"status": "ok", "tjeneste": "ruter"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=_PORT)
