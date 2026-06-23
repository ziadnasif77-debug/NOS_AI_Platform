import os
import sys
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

# Global modell-referanse — kan byttes ut uten omstart via /last-inn-modeller-pa-nytt
_modell_lås = threading.Lock()

app = FastAPI(title="NAV OCR-tjeneste")


def pdf_til_bilde(pdf_sti: str, utgang_sti: str) -> str:
    """Konverterer første side i PDF til PNG for OpenCV-klassifisering."""
    dok = fitz.open(pdf_sti)
    side = dok[0]
    pix = side.get_pixmap(matrix=fitz.Matrix(2, 2))
    pix.save(utgang_sti)
    dok.close()
    return utgang_sti


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
    # HTRflow navngir output etter original filnavn, ikke fil_id
    stamme = Path(pdf_sti).stem
    return {
        "raa": f"{BEHANDLET_STI}/raw/{stamme}.json",
        "renset": f"{BEHANDLET_STI}/renset/{stamme}.json",
        "alto": f"{BEHANDLET_STI}/alto/{stamme}.xml",
        "page": f"{BEHANDLET_STI}/page/{stamme}.xml",
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


def kjor_paddleocr(bilde_sti: str, fil_id: str) -> dict:
    """
    PaddleOCR for enkle trykte skjemaer — returnerer tokens og bokser
    i tillegg til tekst, slik at LayoutLMv3 kan bruke layout-informasjonen.
    """
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
                # Normaliser boks til [x0, y0, x1, y1] format
                x_koord = [p[0] for p in boks_raa]
                y_koord = [p[1] for p in boks_raa]
                bokser.append([int(min(x_koord)), int(min(y_koord)),
                                int(max(x_koord)), int(max(y_koord))])
        fulltekst = "\n".join(tekst_linjer)
        utgang_sti = f"{BEHANDLET_STI}/renset/{fil_id}.json"
        lagre_json({
            "fil_id": fil_id,
            "tekst": fulltekst,
            "tokens": tokens,
            "bokser": bokser,
            "konfidens": 0.95,
        }, utgang_sti)
        return {"renset": utgang_sti, "raa": utgang_sti}
    except Exception as feil:
        logger.error(f"PaddleOCR-feil: {feil}")
        raise


def kjor_ocr(pdf_sti: str, fil_id: str, dokumenttype: str, bilde_sti: str = "") -> dict:
    """
    Kjorer riktig OCR-modell basert på dokumenttype.
    PaddleOCR for enkle trykte skjemaer (returnerer tokens+bokser for LayoutLMv3).
    Returnerer output-stier og beregnet konfidenspoeng.
    """
    if dokumenttype == HANDSKRIFT:
        output = kjor_htrflow(pdf_sti, fil_id)
    elif dokumenttype == TABELL:
        output = kjor_marker(pdf_sti, fil_id)
    elif dokumenttype == TRYKT and bilde_sti:
        # PaddleOCR for trykte skjemaer — gir tokens+bokser til LayoutLMv3
        try:
            output = kjor_paddleocr(bilde_sti, fil_id)
        except Exception:
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
        "bilde_sti": bilde_sti,
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
        # Steg 1: Konverter første PDF-side til bilde og forbehandle
        raa_bilde_sti = f"/tmp/{fil_id}_side0.png"
        forbehandlet_sti = f"/tmp/{fil_id}_forbehandlet.png"
        pdf_til_bilde(pdf_sti, raa_bilde_sti)
        forbehandle_bilde(raa_bilde_sti, forbehandlet_sti)

        # Klassifiser dokumenttype basert på forbehandlet bilde
        dokumenttype = klassifiser_side(forbehandlet_sti)
        logger.info(f"Dokumenttype: {dokumenttype}")

        # Steg 2: Kjor OCR og hent konfidenspoeng (send forbehandlet bilde til PaddleOCR)
        ocr_resultat = kjor_ocr(pdf_sti, fil_id, dokumenttype, bilde_sti=forbehandlet_sti)
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
                "bilde_sti": ocr_resultat.get("bilde_sti"),  # for LayoutLMv3
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
    Laster inn oppdaterte OCR-modeller etter finjustering uten omstart.
    Kalles av eksporter_fra_label_studio.etter_finjustering().
    Tilsvarer feedback-pilen i arkitektur__1_.svg som peker tilbake til lag 4 OCR.
    """
    def _last_i_bakgrunn():
        with _modell_lås:
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
            # Thread per fil — flere filer behandles parallelt
            threading.Thread(
                target=self._behandle_med_forsinkelse,
                args=(hendelse.src_path,),
                daemon=True
            ).start()

    @staticmethod
    def _behandle_med_forsinkelse(sti: str):
        time.sleep(1)  # Venter på at filen er ferdig skrevet
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
