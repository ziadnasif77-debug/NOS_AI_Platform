"""
Lag 0 — Preprocessing Worker
Vurderer bildekvalitet og klassifiserer dokumenttype.
"""
import sys
import os
import logging
import socket

sys.path.insert(0, "/app")
from config.config_loader import CONFIG
from delt.konstanter import HANDSKRIFT, TRYKT, TABELL, BLANDET
from tjenester.workers.base_worker import BaseWorker

logger = logging.getLogger(__name__)

WORKER_ID = f"lag0-{socket.gethostname()}"


class PreprocessingWorker(BaseWorker):

    def __init__(self):
        cfg = CONFIG["redis"]
        super().__init__(
            worker_id=WORKER_ID,
            queue_name=cfg["kooer"]["preprocess"],
            dlq_name=cfg["dlq"]["preprocess"],
            running_state="PREPROCESSING",
            done_state="OCR_PROCESSING",
        )

    def process(self, job: dict, pg_conn) -> dict:
        job_id = job["job_id"]
        fil_sti = job["fil_sti"]
        terskel = CONFIG["terskler"]["bildekvalitet"]

        score, dokumenttype = self._analyser(fil_sti)
        godkjent = score >= terskel

        if not godkjent:
            project_id = CONFIG["label_studio"]["prosjekter"]["lag0"]
            self.send_til_label_studio(
                job_id=job_id,
                image_path=fil_sti,
                ocr_text="",
                project_id=project_id,
                stage="bildekvalitet",
            )

        return {
            "job_id": job_id,
            "document_type": dokumenttype,
            "quality_score": round(score, 4),
            "quality_approved": godkjent,
            "preprocessed_path": fil_sti,
            "rejection_reason": None if godkjent else "lav_bildekvalitet",
        }

    def _analyser(self, fil_sti: str) -> tuple:
        try:
            import cv2
            import numpy as np

            bilde = cv2.imread(fil_sti, cv2.IMREAD_GRAYSCALE)
            if bilde is None:
                return 0.0, TRYKT

            lap_var = cv2.Laplacian(bilde, cv2.CV_64F).var()
            score = min(lap_var / 1000.0, 1.0)
            dokumenttype = self._klassifiser(bilde)
            return score, dokumenttype

        except ImportError:
            return 0.8, TRYKT

    def _klassifiser(self, bilde) -> str:
        import cv2
        import numpy as np

        _, binær = cv2.threshold(bilde, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        hvit_andel = np.sum(binær == 255) / binær.size

        if hvit_andel > 0.90:
            return TRYKT
        elif hvit_andel > 0.70:
            return BLANDET
        else:
            return HANDSKRIFT


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    PreprocessingWorker().run()
