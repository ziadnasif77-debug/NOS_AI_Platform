"""
Lag 1 — OCR Worker
Kjører riktig OCR-motor basert på dokumenttype.
"""
import sys
import os
import logging
import socket
import threading

sys.path.insert(0, "/app")
from config.config_loader import CONFIG
from delt.konstanter import HANDSKRIFT, TRYKT, TABELL, BLANDET
from delt.skjemaer import PreprocessResultat
from tjenester.workers.base_worker import BaseWorker

logger = logging.getLogger(__name__)

WORKER_ID = f"lag1-{socket.gethostname()}"
_GPU_SEM = None


def _gpu_semaphore():
    global _GPU_SEM
    if _GPU_SEM is None:
        maks = CONFIG["gpu"].get("maks_ocr_jobber", 2)
        _GPU_SEM = threading.Semaphore(maks)
    return _GPU_SEM


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

    def process(self, job: dict, pg_conn) -> dict:
        job_id = job["job_id"]
        preprocess = PreprocessResultat.model_validate(job["forrige_resultat"])
        fil_sti = preprocess.preprocessed_path
        dokumenttype = preprocess.document_type
        terskel = CONFIG["terskler"]["ocr_konfidens"] / 100.0

        with _gpu_semaphore():
            tekst, konfidens, tokens, bokser, modell = self._kjor_ocr(
                fil_sti, dokumenttype
            )

        godkjent = konfidens >= terskel
        if not godkjent:
            project_id = CONFIG["label_studio"]["prosjekter"]["lag2"]
            self.send_til_label_studio(
                job_id=job_id,
                image_path=fil_sti,
                ocr_text=tekst,
                project_id=project_id,
                stage="lav_ocr_konfidens",
            )

        return {
            "job_id": job_id,
            "text": tekst,
            "confidence": round(konfidens, 4),
            "tokens": tokens,
            "boxes": bokser,
            "ocr_model_used": modell,
            "document_type": dokumenttype,
            "raw_path": fil_sti,
            "clean_path": fil_sti,
            "confidence_approved": godkjent,
        }

    def _kjor_ocr(self, fil_sti: str, dokumenttype: str):
        if dokumenttype == HANDSKRIFT:
            return self._trocr(fil_sti)
        elif dokumenttype == TABELL:
            return self._marker(fil_sti)
        elif dokumenttype == BLANDET:
            return self._paddle_og_marker(fil_sti)
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
            from transformers import TrOCRProcessor, VisionEncoderDecoderModel
            from PIL import Image
            import torch

            modell_sti = CONFIG["modeller"]["trocr"]
            processor = TrOCRProcessor.from_pretrained(modell_sti)
            modell = VisionEncoderDecoderModel.from_pretrained(modell_sti)
            bilde = Image.open(fil_sti).convert("RGB")
            pixel_values = processor(images=bilde, return_tensors="pt").pixel_values
            with torch.no_grad():
                generated_ids = modell.generate(pixel_values)
            tekst = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
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

    def _paddle_og_marker(self, fil_sti: str):
        tekst_p, k_p, tokens_p, bokser_p, _ = self._paddleocr(fil_sti)
        tekst_m, k_m, _, _, _ = self._marker(fil_sti)
        kombinert = f"{tekst_p}\n{tekst_m}".strip()
        snitt = (k_p + k_m) / 2
        return kombinert, snitt, tokens_p, bokser_p, "paddleocr+marker"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    OCRWorker().run()
