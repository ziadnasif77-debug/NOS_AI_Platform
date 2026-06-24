import sys
import threading
import subprocess
from pathlib import Path

sys.path.insert(0, "/config")
sys.path.insert(0, "/delt")
from config.config_loader import CONFIG

if not CONFIG["lag"]["lag2_ocr"]:
    raise SystemExit("Lag 2 (OCR) er deaktivert i config.yaml")

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
import requests

app = FastAPI(title="NAV Lag 2 — OCR")

_PORT = CONFIG["porter"]["lag2"]
_BEHANDLET_STI = CONFIG["stier"]["behandlet"]
_MODELLER_STI = CONFIG["stier"]["modeller"]
_MAKS_OCR_JOBBER = CONFIG["gpu"]["maks_ocr_jobber"]
_TROCR_MODELL = CONFIG["modeller"]["trocr"]

_ocr_semafor = threading.Semaphore(_MAKS_OCR_JOBBER)

HANDSKRIFT = "handskrift"
TRYKT = "trykt"
TABELL = "tabell"


class OcrInn(BaseModel):
    pdf_sti: str
    fil_id: str
    dokumenttype: str
    bilde_sti: str


def _lagre_json(data: dict, sti: str) -> None:
    import json
    Path(sti).parent.mkdir(parents=True, exist_ok=True)
    with open(sti, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _les_json(sti: str) -> dict:
    import json
    with open(sti, "r", encoding="utf-8") as f:
        return json.load(f)


def kjor_htrflow(pdf_sti: str, fil_id: str) -> dict:
    pipeline_sti = Path(__file__).parent.parent / "ocr" / "pipeline.yaml"
    try:
        resultat = subprocess.run(
            ["htrflow", "pipeline", str(pipeline_sti), pdf_sti],
            capture_output=True, text=True, timeout=300
        )
        if resultat.returncode != 0:
            raise RuntimeError(f"HTRflow feilet: {resultat.stderr}")
    except Exception as feil:
        raise RuntimeError(f"HTRflow-feil: {feil}")
    stamme = Path(pdf_sti).stem
    return {
        "raa": f"{_BEHANDLET_STI}/raw/{stamme}.json",
        "renset": f"{_BEHANDLET_STI}/renset/{stamme}.json",
        "alto": f"{_BEHANDLET_STI}/alto/{stamme}.xml",
        "page": f"{_BEHANDLET_STI}/page/{stamme}.xml",
    }


def kjor_marker(pdf_sti: str, fil_id: str) -> dict:
    try:
        from marker.convert import convert_single_pdf
        from marker.models import load_all_models
        modeller = load_all_models()
        fulltekst, bilder, metadata = convert_single_pdf(
            pdf_sti, modeller, langs=["no"]
        )
        utgang_sti = f"{_BEHANDLET_STI}/renset/{fil_id}.json"
        _lagre_json({"fil_id": fil_id, "tekst": fulltekst, "metadata": metadata}, utgang_sti)
        return {"renset": utgang_sti, "raa": utgang_sti}
    except Exception as feil:
        raise RuntimeError(f"Marker-feil: {feil}")


def kjor_paddleocr(bilde_sti: str, fil_id: str) -> dict:
    try:
        from paddleocr import PaddleOCR
        ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        resultat = ocr.ocr(bilde_sti, cls=True)
        tekst_linjer = []
        tokens = []
        bokser = []
        if resultat and resultat[0]:
            for linje in resultat[0]:
                boks_raa, (tekst, konf) = linje
                tekst_linjer.append(tekst)
                tokens.append(tekst)
                x_koord = [p[0] for p in boks_raa]
                y_koord = [p[1] for p in boks_raa]
                bokser.append([int(min(x_koord)), int(min(y_koord)),
                                int(max(x_koord)), int(max(y_koord))])
        fulltekst = "\n".join(tekst_linjer)
        utgang_sti = f"{_BEHANDLET_STI}/renset/{fil_id}.json"
        _lagre_json({
            "fil_id": fil_id,
            "tekst": fulltekst,
            "tokens": tokens,
            "bokser": bokser,
            "konfidens": 0.95,
        }, utgang_sti)
        return {"renset": utgang_sti, "raa": utgang_sti}
    except Exception as feil:
        raise RuntimeError(f"PaddleOCR-feil: {feil}")


def kjor_ocr_intern(pdf_sti: str, fil_id: str, dokumenttype: str, bilde_sti: str) -> dict:
    with _ocr_semafor:
        if dokumenttype == HANDSKRIFT:
            output = kjor_htrflow(pdf_sti, fil_id)
        elif dokumenttype == TABELL:
            output = kjor_marker(pdf_sti, fil_id)
        elif dokumenttype == TRYKT and bilde_sti:
            try:
                output = kjor_paddleocr(bilde_sti, fil_id)
            except Exception:
                output = kjor_marker(pdf_sti, fil_id)
        else:
            output = kjor_htrflow(pdf_sti, fil_id)

        raa_tekst = ""
        tokens = []
        bokser = []
        konfidens = 1.0
        try:
            raa_sti = output.get("raa", "")
            if raa_sti and Path(raa_sti).exists():
                raa_data = _les_json(raa_sti)
                raa_tekst = raa_data.get("tekst", "")
                tokens = raa_data.get("tokens", [])
                bokser = raa_data.get("bokser", [])
                konfidens = float(raa_data.get("konfidens", 1.0))
        except Exception:
            pass

        return {
            "tekst": raa_tekst,
            "tokens": tokens,
            "bokser": bokser,
            "konfidens": konfidens,
            "raa_sti": output.get("raa", ""),
            "renset_sti": output.get("renset", ""),
            "bilde_sti": bilde_sti,
        }


@app.post("/kjor-ocr")
async def kjor_ocr_endepunkt(data: OcrInn):
    resultat = kjor_ocr_intern(
        data.pdf_sti, data.fil_id, data.dokumenttype, data.bilde_sti
    )
    return resultat


@app.get("/helse")
async def helse():
    return {"status": "ok", "lag": 2, "aktiv": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=_PORT)
