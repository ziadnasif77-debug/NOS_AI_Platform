import os
import sys
import time
import subprocess
import requests
import uvicorn
from fastapi import FastAPI
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

sys.path.insert(0, "/delt")
sys.path.insert(0, "/skript")
from delt.verktøy import konfigurer_logging, lagre_json, les_json, generer_fil_id
from delt.skjemaer import DokumentInntak, SideResultat
from delt.konstanter import HANDSKRIFT, TRYKT, TABELL, BLANDET
from klassifiserer import klassifiser_side, forbehandle_bilde

logger = konfigurer_logging("ocr-tjeneste")

INNTAK_STI = os.environ.get("INNTAK_STI", "/data/inntak")
BEHANDLET_STI = os.environ.get("BEHANDLET_STI", "/data/behandlet")
MODELLER_STI = os.environ.get("MODELLER_STI", "/modeller")
NLP_URL = os.environ.get("NLP_URL", "http://nlp:8002")
KONFIDENS_TERSKEL = float(os.environ.get("KONFIDENS_TERSKEL", "85")) / 100

# Holder styr på siste kjente konfidenspoeng for dashboard-endepunktet
_siste_konfidens: dict = {"konfidens": None, "fil_id": None, "vei": None}

app = FastAPI(title="NAV OCR-tjeneste")


def kjor_htrflow(pdf_sti: str, fil_id: str) -> dict:
    pipeline_sti = Path(__file__).parent / "pipeline.yaml"
    try:
        resultat = subprocess.run(
            ["htrflow", "pipeline", str(pipeline_sti), pdf_sti],
            capture_output=True,
            text=True,
            timeout=300
        )
        if resultat.returncode != 0:
            raise RuntimeError(f"HTRflow feilet: {resultat.stderr}")
    except Exception as feil:
        logger.error(f"HTRflow-feil: {feil}")
        raise
    return {
        "raa": f"{BEHANDLET_STI}/raw/{fil_id}.json",
        "renset": f"{BEHANDLET_STI}/renset/{fil_id}.json",
        "alto": f"{BEHANDLET_STI}/alto/{fil_id}.xml",
        "page": f"{BEHANDLET_STI}/page/{fil_id}.xml",
    }


def kjor_marker(pdf_sti: str, fil_id: str) -> dict:
    try:
        from marker.convert import convert_single_pdf
        from marker.models import load_all_models
        modeller = load_all_models()
        fulltekst, bilder, metadata = convert_single_pdf(
            pdf_sti, modeller, langs=["no"]
        )
        utgang_sti = f"{BEHANDLET_STI}/renset/{fil_id}.json"
        lagre_json({"fil_id": fil_id, "tekst": fulltekst, "metadata": metadata}, utgang_sti)
        return {"renset": utgang_sti, "raa": utgang_sti}
    except Exception as feil:
        logger.error(f"Marker-feil: {feil}")
        raise


def kjor_ocr(pdf_sti: str, fil_id: str, dokumenttype: str) -> dict:
    """
    Kjorer riktig OCR-modell basert på dokumenttype.
    Returnerer output-stier og beregnet konfidenspoeng.
    """
    if dokumenttype == HANDSKRIFT:
        output = kjor_htrflow(pdf_sti, fil_id)
    elif dokumenttype in [TRYKT, TABELL]:
        output = kjor_marker(pdf_sti, fil_id)
    else:
        output = kjor_htrflow(pdf_sti, fil_id)

    # Les konfidenspoeng fra raw-output
    raa_tekst = ""
    konfidens = 1.0
    try:
        raa_sti = output.get("raa", "")
        if raa_sti and Path(raa_sti).exists():
            raa_data = les_json(raa_sti)
            raa_tekst = raa_data.get("tekst", "")
            konfidens = float(raa_data.get("konfidens", 1.0))
    except Exception:
        pass

    return {
        **output,
        "raa_tekst": raa_tekst,
        "konfidens": konfidens,
        "dokumenttype": dokumenttype,
        "metadata": {"dokumenttype": dokumenttype},
    }


def behandle_pdf(pdf_sti: str) -> None:
    """
    Fullstendig behandling av én PDF-fil.

    Branching eksakt som vist i arkitektur__1_.svg:
      konfidens >= 85% → NLP-tjenesten
      konfidens <  85% → Label Studio (sidebranch)
    De to veiene er gjensidig utelukkende.
    """
    filnavn = Path(pdf_sti).name
    fil_id = generer_fil_id(filnavn)
    logger.info(f"Starter behandling av: {filnavn} (ID: {fil_id})")
    try:
        # Steg 1: Klassifiser dokumenttype
        dokumenttype = klassifiser_side(pdf_sti)
        logger.info(f"Dokumenttype: {dokumenttype}")

        # Steg 2: Kjor OCR og hent konfidenspoeng
        ocr_resultat = kjor_ocr(pdf_sti, fil_id, dokumenttype)
        konfidens = ocr_resultat["konfidens"]

        # Oppdater siste-konfidens for dashboard-endepunktet
        global _siste_konfidens

        # Steg 3: EKSPLISITT BRANCH — som vist i arkitektur__1_.svg
        if konfidens >= KONFIDENS_TERSKEL:
            # Vei A: Hoy konfidens → NLP
            logger.info(
                f"Konfidens {konfidens:.0%} >= {KONFIDENS_TERSKEL:.0%} terskel "
                f"→ sender til NLP"
            )
            _siste_konfidens = {"konfidens": konfidens, "fil_id": fil_id, "vei": "nlp"}
            _send_til_nlp(fil_id, filnavn, dokumenttype, ocr_resultat)
        else:
            # Vei B: Lav konfidens → Label Studio (sidebranch)
            logger.info(
                f"Konfidens {konfidens:.0%} < {KONFIDENS_TERSKEL:.0%} terskel "
                f"→ sender til Label Studio"
            )
            _siste_konfidens = {"konfidens": konfidens, "fil_id": fil_id, "vei": "label_studio"}
            _send_til_label_studio(fil_id, pdf_sti, ocr_resultat)

        logger.info(f"Fullfort: {filnavn}")
    except Exception as feil:
        logger.error(f"Feil ved behandling av {filnavn}: {feil}")


def _send_til_nlp(fil_id: str, filnavn: str,
                  dokumenttype: str, ocr_resultat: dict) -> None:
    """Sender dokumentet til NLP-tjenesten. Kalles KUN naar konfidens >= terskel."""
    try:
        requests.post(
            f"{NLP_URL}/behandle",
            json={
                "fil_id": fil_id,
                "filnavn": filnavn,
                "dokumenttype": dokumenttype,
                "renset_sti": ocr_resultat.get("renset"),
            },
            timeout=30
        )
    except requests.RequestException as feil:
        logger.warning(f"Kunne ikke varsle NLP: {feil}")


def _send_til_label_studio(fil_id: str, pdf_sti: str, ocr_resultat: dict) -> None:
    """
    Sender dokument til Label Studio for menneskelig korreksjon.
    Kalles KUN naar konfidens < KONFIDENS_TERSKEL (85%).
    Tilsvarer den gule stiplede branchen i arkitektur__1_.svg.
    """
    try:
        from send_til_label_studio import send_til_gjennomgang
        sendt = send_til_gjennomgang(
            fil_id=fil_id,
            bilde_sti=pdf_sti,
            raa_tekst=ocr_resultat.get("raa_tekst", ""),
            konfidens=ocr_resultat.get("konfidens", 0.0),
            metadata=ocr_resultat.get("metadata", {})
        )
        if sendt:
            logger.info(f"Sendt til Label Studio: {fil_id}")
    except Exception as feil:
        logger.error(f"Feil ved sending til Label Studio: {feil}")


# ══ FastAPI-endepunkter ══

@app.get("/helse")
async def helse():
    return {"status": "ok", "tjeneste": "ocr"}


@app.get("/siste-konfidens")
async def siste_konfidens():
    """
    Returnerer konfidenspoeng for siste behandlede dokument.
    Brukes av pipeline_dashboard for aa vise hvilken vei dokumentet tok.
    """
    return _siste_konfidens


@app.post("/last-inn-modeller-pa-nytt")
async def last_inn_modeller_pa_nytt():
    """
    Ber OCR-tjenesten laste inn oppdaterte modeller etter finjustering.
    Kalles av eksporter_fra_label_studio.etter_finjustering().
    Tilsvarer feedback-pilen i arkitektur__1_.svg som peker tilbake til lag 4 OCR.
    """
    logger.info("Mottok foresporsel om aa laste inn modeller pa nytt etter finjustering")
    return {"status": "ok", "melding": "Modeller vil lastes inn ved neste oppstart"}


class NyFilHaandterer(FileSystemEventHandler):
    def on_created(self, hendelse):
        if not hendelse.is_directory and hendelse.src_path.endswith(".pdf"):
            logger.info(f"Ny fil oppdaget: {hendelse.src_path}")
            time.sleep(1)
            behandle_pdf(hendelse.src_path)


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
    import threading
    wd_trad = threading.Thread(target=start_watchdog, daemon=True)
    wd_trad.start()
    uvicorn.run(app, host="0.0.0.0", port=8001)
