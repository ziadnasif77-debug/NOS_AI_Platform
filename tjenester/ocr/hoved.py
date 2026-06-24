import os
import sys
import json
import time
import threading
import subprocess
import requests
import uvicorn
import fitz  # PyMuPDF
from fastapi import FastAPI
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

sys.path.insert(0, "/config")
sys.path.insert(0, "/delt")
sys.path.insert(0, "/skript")
from config.config_loader import CONFIG
from delt.verktøy import konfigurer_logging, lagre_json, les_json, generer_fil_id
from delt.skjemaer import DokumentInntak, SideResultat
from delt.konstanter import HANDSKRIFT, TRYKT, TABELL, BLANDET

logger = konfigurer_logging("ocr-tjeneste")

INNTAK_STI = os.environ.get("INNTAK_STI", CONFIG["stier"]["inntak"])
BEHANDLET_STI = os.environ.get("BEHANDLET_STI", CONFIG["stier"]["behandlet"])
MODELLER_STI = os.environ.get("MODELLER_STI", CONFIG["stier"]["modeller"])
REDIS_URL = os.environ.get("REDIS_URL", CONFIG["redis"]["url"])

LAG_URLS = {
    "lag0": f"http://lag0:{CONFIG['porter']['lag0']}",
    "lag1": f"http://lag1:{CONFIG['porter']['lag1']}",
    "lag2": f"http://lag2:{CONFIG['porter']['lag2']}",
    "lag3": f"http://lag3:{CONFIG['porter']['lag3']}",
    "lag4": f"http://lag4:{CONFIG['porter']['lag4']}",
    "lag5": f"http://lag5:{CONFIG['porter']['lag5']}",
    "ruter": f"http://ruter:{CONFIG['porter']['ruter']}",
}

# Holder styr på siste kjente konfidenspoeng for dashboard-endepunktet
_siste_konfidens: dict = {"konfidens": None, "fil_id": None, "vei": None}

app = FastAPI(title="NAV OCR-tjeneste")


def _oppdater_jobb(jobb_id: str, status: str, detaljer: dict = None) -> None:
    """Oppdaterer jobbstatus i Redis. Taus ved feil."""
    if not jobb_id or not REDIS_URL:
        return
    try:
        import redis
        r = redis.from_url(REDIS_URL, decode_responses=True)
        data = {"jobb_id": jobb_id, "status": status, **(detaljer or {})}
        r.setex(f"jobb:{jobb_id}", CONFIG["redis"]["ttl_sekunder"], json.dumps(data))
    except Exception:
        pass


def _les_jobb_id(pdf_sti: str) -> str:
    """Leser jobb_id fra sidecar-fil generert av API ved opplasting."""
    sidecar = Path(pdf_sti).with_suffix(".jobb.json")
    if sidecar.exists():
        try:
            with open(sidecar, encoding="utf-8") as f:
                return json.load(f).get("jobb_id", "")
        except Exception:
            pass
    return ""


def _send_til_nlp(fil_id: str, filnavn: str,
                  dokumenttype: str, ocr_resultat: dict) -> None:
    """Sender dokumentet til NLP-tjenesten (legacy-kompatibilitet)."""
    try:
        requests.post(
            f"{LAG_URLS['lag3']}/analyser",
            json={
                "fil_id": fil_id,
                "tekst": ocr_resultat.get("tekst", ""),
                "tokens": ocr_resultat.get("tokens", []),
                "bokser": ocr_resultat.get("bokser", []),
                "bilde_sti": ocr_resultat.get("bilde_sti", ""),
            },
            timeout=60
        )
    except requests.RequestException as feil:
        logger.warning(f"Kunne ikke varsle NLP/Lag3: {feil}")


def _send_til_label_studio(fil_id: str, pdf_sti: str, ocr_resultat: dict) -> None:
    """Sender dokument til Label Studio for menneskelig korreksjon."""
    try:
        from send_til_label_studio import send_til_gjennomgang
        prosjekt_id = ocr_resultat.get("prosjekt_id", CONFIG["label_studio"]["prosjekter"]["lag0"])
        send_til_gjennomgang(
            fil_id=fil_id,
            bilde_sti=pdf_sti,
            raa_tekst=ocr_resultat.get("tekst", ""),
            konfidens=ocr_resultat.get("konfidens", 0.0),
            metadata={**ocr_resultat.get("metadata", {}), "prosjekt_id": prosjekt_id}
        )
        logger.info(f"Sendt til Label Studio: {fil_id}")
    except Exception as feil:
        logger.error(f"Feil ved sending til Label Studio: {feil}")


def behandle_pdf(pdf_sti: str) -> None:
    """
    Fullstendig behandling av én PDF-fil via de nye lagene (HTTP).
    """
    filnavn = Path(pdf_sti).name
    fil_id = generer_fil_id(filnavn)
    jobb_id = _les_jobb_id(pdf_sti)
    _oppdater_jobb(jobb_id, "pagar", {"fil_id": fil_id})

    try:
        # Lag 0: PDF → bilde + kvalitetssjekk
        bilde_svar = requests.post(f"{LAG_URLS['lag0']}/pdf-til-bilde",
            json={"pdf_sti": pdf_sti, "fil_id": fil_id}, timeout=30).json()
        bilde_sti = bilde_svar["bilde_sti"]

        kvalitet_svar = requests.post(f"{LAG_URLS['lag0']}/sjekk-kvalitet",
            json={"bilde_sti": bilde_sti}, timeout=10).json()

        forbehandle_svar = requests.post(f"{LAG_URLS['lag0']}/forbehandle",
            json={"bilde_sti": bilde_sti, "fil_id": fil_id}, timeout=30).json()
        forbehandlet_sti = forbehandle_svar["forbehandlet_sti"]

        # Lag 1: Klassifiser dokumenttype
        klasse_svar = requests.post(f"{LAG_URLS['lag1']}/klassifiser",
            json={"bilde_sti": forbehandlet_sti}, timeout=10).json()
        dokumenttype = klasse_svar["type"]

        # Lag 2: OCR
        ocr_svar = requests.post(f"{LAG_URLS['lag2']}/kjor-ocr",
            json={"pdf_sti": pdf_sti, "fil_id": fil_id,
                  "dokumenttype": dokumenttype, "bilde_sti": forbehandlet_sti},
            timeout=120).json()

        # Lag 3: NLP
        nlp_svar = requests.post(f"{LAG_URLS['lag3']}/analyser",
            json={"fil_id": fil_id, "tekst": ocr_svar.get("tekst", ""),
                  "tokens": ocr_svar.get("tokens", []),
                  "bokser": ocr_svar.get("bokser", []),
                  "bilde_sti": forbehandlet_sti},
            timeout=60).json()

        # Lag 4: Valider
        lag4_svar = requests.post(f"{LAG_URLS['lag4']}/valider",
            json={"fil_id": fil_id, "dokumenttype": nlp_svar.get("dokumenttype", "ukjent"),
                  "felter": nlp_svar},
            timeout=10).json()

        # Lag 5 (valgfri)
        lag5_svar = None
        if CONFIG["lag"]["lag5_kryssvalidering"]:
            try:
                lag5_svar = requests.post(f"{LAG_URLS['lag5']}/kryssvalider",
                    json={"fil_id": fil_id, "tekst": ocr_svar.get("tekst", ""),
                          "metadata": nlp_svar},
                    timeout=30).json()
            except Exception:
                pass

        # Ruter: bestem destinasjon
        ruter_svar = requests.post(f"{LAG_URLS['ruter']}/ruter",
            json={"fil_id": fil_id, "lag0": kvalitet_svar, "lag1": klasse_svar,
                  "lag2": ocr_svar, "lag3": nlp_svar, "lag4": lag4_svar},
            timeout=10).json()

        if ruter_svar["destinasjon"] == "sok":
            _oppdater_jobb(jobb_id, "nlp_pagar", {"fil_id": fil_id})
            _send_til_nlp(fil_id, filnavn, dokumenttype, ocr_svar)
            _oppdater_jobb(jobb_id, "fullfort", {"fil_id": fil_id})
        else:
            prosjekt_id = ruter_svar.get("prosjekt_id", 1)
            _oppdater_jobb(jobb_id, "gjennomgang", {"fil_id": fil_id, "grunn": ruter_svar["grunn"]})
            _send_til_label_studio(fil_id, pdf_sti, {
                **ocr_svar,
                "metadata": {"dokumenttype": dokumenttype},
                "prosjekt_id": prosjekt_id,
            })

    except Exception as feil:
        logger.error(f"Pipeline-feil for {filnavn}: {feil}")
        _oppdater_jobb(jobb_id, "feil", {"feil": str(feil)})


# ══ FastAPI-endepunkter ══

@app.get("/helse")
async def helse():
    return {"status": "ok", "tjeneste": "ocr"}


@app.get("/siste-konfidens")
async def siste_konfidens():
    return _siste_konfidens


@app.post("/last-inn-modeller-pa-nytt")
async def last_inn_modeller_pa_nytt():
    def _last_i_bakgrunn():
        logger.info("Laster inn oppdaterte OCR-modeller fra finjustering...")
        try:
            from marker.models import load_all_models
            load_all_models()
            logger.info("Marker OCR-modeller lastet inn på nytt")
        except Exception as feil:
            logger.warning(f"Marker re-load feilet: {feil}")
        logger.info("Modellinnlasting fullført")

    threading.Thread(target=_last_i_bakgrunn, daemon=True).start()
    return {"status": "ok", "melding": "Modellinnlasting startet i bakgrunnen"}


class NyFilHaandterer(FileSystemEventHandler):
    def on_created(self, hendelse):
        if not hendelse.is_directory and hendelse.src_path.endswith(".pdf"):
            logger.info(f"Ny fil oppdaget: {hendelse.src_path}")
            threading.Thread(
                target=self._behandle_med_forsinkelse,
                args=(hendelse.src_path,),
                daemon=True
            ).start()

    @staticmethod
    def _behandle_med_forsinkelse(sti: str):
        time.sleep(1)
        behandle_pdf(sti)


def start_watchdog():
    logger.info(f"OCR-tjeneste starter. Overvaaker: {INNTAK_STI}")
    Path(INNTAK_STI).mkdir(parents=True, exist_ok=True)
    observer = Observer()
    observer.schedule(NyFilHaandterer(), INNTAK_STI, recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    wd_trad = threading.Thread(target=start_watchdog, daemon=True)
    wd_trad.start()
    uvicorn.run(app, host="0.0.0.0", port=8001)
