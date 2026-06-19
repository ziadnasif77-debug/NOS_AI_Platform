import os
import sys
import time
import subprocess
import requests
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

sys.path.insert(0, "/delt")
from delt.verktøy import konfigurer_logging, lagre_json, generer_fil_id
from delt.skjemaer import DokumentInntak, SideResultat
from delt.konstanter import HANDSKRIFT, TRYKT, TABELL, BLANDET
from klassifiserer import klassifiser_side, forbehandle_bilde

logger = konfigurer_logging("ocr-tjeneste")

INNTAK_STI = os.environ.get("INNTAK_STI", "/data/inntak")
BEHANDLET_STI = os.environ.get("BEHANDLET_STI", "/data/behandlet")
MODELLER_STI = os.environ.get("MODELLER_STI", "/modeller")
NLP_URL = os.environ.get("NLP_URL", "http://nlp:8002")
KONFIDENS_TERSKEL = float(os.environ.get("KONFIDENS_TERSKEL", "85")) / 100


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
        lagre_json({
            "fil_id": fil_id,
            "tekst": fulltekst,
            "metadata": metadata
        }, utgang_sti)
        return {"renset": utgang_sti, "raa": utgang_sti}
    except Exception as feil:
        logger.error(f"Marker-feil: {feil}")
        raise


def behandle_pdf(pdf_sti: str) -> None:
    filnavn = Path(pdf_sti).name
    fil_id = generer_fil_id(filnavn)
    logger.info(f"Starter behandling av: {filnavn} (ID: {fil_id})")
    try:
        dokumenttype = klassifiser_side(pdf_sti)
        logger.info(f"Dokumenttype: {dokumenttype}")
        if dokumenttype == HANDSKRIFT:
            output = kjor_htrflow(pdf_sti, fil_id)
        elif dokumenttype in [TRYKT, TABELL]:
            output = kjor_marker(pdf_sti, fil_id)
        else:
            output = kjor_htrflow(pdf_sti, fil_id)
        _send_til_nlp(fil_id, filnavn, dokumenttype, output)
        logger.info(f"Fullfort: {filnavn}")
    except Exception as feil:
        logger.error(f"Feil ved behandling av {filnavn}: {feil}")


def _send_til_nlp(fil_id: str, filnavn: str,
                  dokumenttype: str, output: dict) -> None:
    try:
        requests.post(
            f"{NLP_URL}/behandle",
            json={
                "fil_id": fil_id,
                "filnavn": filnavn,
                "dokumenttype": dokumenttype,
                "renset_sti": output.get("renset"),
            },
            timeout=30
        )
    except requests.RequestException as feil:
        logger.warning(f"Kunne ikke varsle NLP: {feil}")


class NyFilHaandterer(FileSystemEventHandler):
    def on_created(self, hendelse):
        if not hendelse.is_directory and hendelse.src_path.endswith(".pdf"):
            logger.info(f"Ny fil oppdaget: {hendelse.src_path}")
            time.sleep(1)
            behandle_pdf(hendelse.src_path)


if __name__ == "__main__":
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
