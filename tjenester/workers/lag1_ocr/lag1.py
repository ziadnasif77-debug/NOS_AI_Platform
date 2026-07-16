"""
Lag 1 — OCR Worker
Kjører riktig OCR-motor basert på dokumenttype.
"""
import sys
import os
import logging
import socket

sys.path.insert(0, "/app")
from config.config_loader import CONFIG
from delt.konstanter import HANDSKRIFT, TRYKT, TABELL, BLANDET
from delt.skjemaer import PreprocessResultat, OCRResultat
from tjenester.workers.base_worker import BaseWorker

logger = logging.getLogger(__name__)

WORKER_ID = f"lag1-{socket.gethostname()}"
MODELLER_STI = os.environ.get("MODELLER_STI", "/modeller")

# NB: GPU-samtidighet begrenses av antall worker-replicas og K8s
# GPU-limits — en in-process-semafor i en enkelt-trådet worker
# begrenset ingenting og er fjernet.


class OCRWorker(BaseWorker):

    def __init__(self):
        cfg = CONFIG["redis"]
        super().__init__(
            worker_id=WORKER_ID,
            queue_name=cfg["kooer"]["ocr"],
            dlq_name=cfg["dlq"]["ocr"],
            running_state="OCR_PROCESSING",
            done_state="NLP_PROCESSING",
        )
        self._trocr_processor = None
        self._trocr_model = None
        self._trocr_available = False
        self._last_trocr()

    def _last_trocr(self):
        """Laster TrOCR én gang ved oppstart — ikke per dokument."""
        try:
            from transformers import TrOCRProcessor, VisionEncoderDecoderModel
            modell_sti = f"{MODELLER_STI}/{CONFIG['modeller']['trocr']}"
            self._trocr_processor = TrOCRProcessor.from_pretrained(modell_sti)
            self._trocr_model = VisionEncoderDecoderModel.from_pretrained(modell_sti)
            self._trocr_model.eval()
            self._trocr_available = True
            logger.info("TrOCR lastet.")
        except Exception as exc:
            logger.warning(
                "TrOCR lasting feilet: %s — handskrift-OCR ikke tilgjengelig.", exc
            )

    def process(self, job: dict, pg_conn) -> dict:
        job_id = job["job_id"]
        preprocess = PreprocessResultat.model_validate(job["forrige_resultat"])
        fil_sti = preprocess.preprocessed_path
        # Marker krever PDF-inndata — bruk enkeltside-PDF-en fra lag0
        # når den finnes, ellers fall tilbake til bildet.
        pdf_sti = preprocess.side_pdf_sti or fil_sti
        dokumenttype = preprocess.document_type
        terskel = CONFIG["terskler"]["ocr_konfidens"] / 100.0

        tekst, konfidens, tokens, bokser, modell = self._kjor_ocr(
            fil_sti, dokumenttype, pdf_sti
        )

        godkjent = konfidens >= terskel
        if not godkjent:
            project_id = CONFIG["label_studio"]["prosjekter"]["ocr_konfidens"]
            self.send_til_label_studio(
                job_id=job_id,
                image_path=fil_sti,
                ocr_text=tekst,
                project_id=project_id,
                stage="lav_ocr_konfidens",
            )

        return OCRResultat(
            job_id=job_id,
            text=tekst,
            confidence=round(konfidens, 4),
            tokens=tokens,
            boxes=bokser,
            ocr_model_used=modell,
            document_type=dokumenttype,
            raw_path=fil_sti,
            clean_path=fil_sti,
            confidence_approved=godkjent,
        ).model_dump()

    def _kjor_ocr(self, fil_sti: str, dokumenttype: str, pdf_sti: str = None):
        pdf_sti = pdf_sti or fil_sti
        if dokumenttype == HANDSKRIFT:
            if not self._trocr_available:
                logger.warning("TrOCR ikke tilgjengelig — bruker PaddleOCR for HANDSKRIFT")
                return self._paddleocr(fil_sti)
            return self._trocr(fil_sti)
        elif dokumenttype == TABELL:
            return self._marker(pdf_sti)
        elif dokumenttype == BLANDET:
            return self._paddle_og_marker(fil_sti, pdf_sti)
        else:
            return self._paddleocr(fil_sti)

    def _paddleocr(self, fil_sti: str):
        try:
            from paddleocr import PaddleOCR
            ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
            resultat = ocr.ocr(fil_sti, cls=True)
            if not resultat or not resultat[0]:
                return "", 0.0, [], [], "paddleocr"
            linjer = resultat[0]
            tekst = " ".join(l[1][0] for l in linjer if l)
            konfidens = sum(l[1][1] for l in linjer if l) / max(len(linjer), 1)
            tokens = [l[1][0] for l in linjer if l]
            bokser = [l[0] for l in linjer if l]
            return tekst, konfidens, tokens, bokser, "paddleocr"
        except Exception as exc:
            logger.warning("PaddleOCR feilet: %s — bruker fallback", exc)
            return f"[OCR-FEIL: {exc}]", 0.0, [], [], "paddleocr-feil"

    def _trocr(self, fil_sti: str):
        try:
            from PIL import Image
            import torch

            bilde = Image.open(fil_sti).convert("RGB")
            pixel_values = self._trocr_processor(images=bilde, return_tensors="pt").pixel_values
            with torch.no_grad():
                generated_ids = self._trocr_model.generate(pixel_values)
            tekst = self._trocr_processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
            return tekst, 0.88, tekst.split(), [], "trocr"
        except Exception as exc:
            logger.warning("TrOCR feilet: %s", exc)
            return "", 0.0, [], [], "trocr-feil"

    def _marker(self, fil_sti: str):
        try:
            from marker.convert import convert_single_pdf
            from marker.models import load_all_models
            modeller = load_all_models()
            full_tekst, _, _ = convert_single_pdf(fil_sti, modeller)
            return full_tekst, 0.90, full_tekst.split(), [], "marker"
        except Exception as exc:
            logger.warning("Marker OCR feilet: %s", exc)
            return "", 0.0, [], [], "marker-feil"

    def _paddle_og_marker(self, fil_sti: str, pdf_sti: str = None):
        tekst_p, k_p, tokens_p, bokser_p, _ = self._paddleocr(fil_sti)
        tekst_m, k_m, _, _, _ = self._marker(pdf_sti or fil_sti)
        kombinert = f"{tekst_p}\n{tekst_m}".strip()
        snitt = (k_p + k_m) / 2
        return kombinert, snitt, tokens_p, bokser_p, "paddleocr+marker"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    OCRWorker().run()
