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
from delt.skjemaer import PreprocessResultat
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

        side_nummer = self._hent_side_nummer(job, job_id, pg_conn)
        side_png, side_pdf = self._render_side(fil_sti, side_nummer, job_id)

        score, dokumenttype = self._analyser(side_png or fil_sti)
        godkjent = score >= terskel

        if not godkjent:
            project_id = CONFIG["label_studio"]["prosjekter"]["bildekvalitet"]
            self.send_til_label_studio(
                job_id=job_id,
                image_path=side_png or fil_sti,
                ocr_text="",
                project_id=project_id,
                stage="bildekvalitet",
            )

        return PreprocessResultat(
            job_id=job_id,
            document_type=dokumenttype,
            quality_score=round(score, 4),
            quality_approved=godkjent,
            preprocessed_path=side_png or fil_sti,
            side_pdf_sti=side_pdf,
            rejection_reason=None if godkjent else "lav_bildekvalitet",
        ).model_dump()

    def _hent_side_nummer(self, job: dict, job_id: str, pg) -> int:
        """Postgres er sannheten — payload kan mangle side_nummer
        (f.eks. ved reconciliation-re-kø eller kubeflow-modus)."""
        if "side_nummer" in job:
            return int(job["side_nummer"])
        try:
            with pg.cursor() as cur:
                cur.execute("SELECT side_nummer FROM jobs WHERE job_id = %s", (job_id,))
                rad = cur.fetchone()
            return int(rad[0]) if rad and rad[0] is not None else 0
        except Exception as exc:
            logger.warning("Kunne ikke hente side_nummer for %s: %s — bruker 0",
                           job_id, exc)
            return 0

    def _render_side(self, fil_sti: str, side_nummer: int, job_id: str):
        """
        Rendrer riktig PDF-side til PNG (for bildebaserte motorer) og
        skriver ut en enkeltside-PDF (for Marker). cv2.imread kan ikke
        lese PDF — uten dette steget fikk alle PDF-er score 0.0/TRYKT
        og kun første side ble noensinne behandlet.
        """
        if not fil_sti.lower().endswith(".pdf"):
            return fil_sti, None   # allerede et bilde
        try:
            import fitz
            with fitz.open(fil_sti) as dok:
                if side_nummer >= dok.page_count:
                    logger.error("Side %d finnes ikke i %s (%d sider)",
                                 side_nummer, fil_sti, dok.page_count)
                    return None, None
                side = dok[side_nummer]
                png_sti = f"{os.path.splitext(fil_sti)[0]}_side{side_nummer}.png"
                side.get_pixmap(matrix=fitz.Matrix(2, 2)).save(png_sti)

                pdf_sti = f"{os.path.splitext(fil_sti)[0]}_side{side_nummer}.pdf"
                with fitz.open() as enkeltside:
                    enkeltside.insert_pdf(dok, from_page=side_nummer,
                                          to_page=side_nummer)
                    enkeltside.save(pdf_sti)
            return png_sti, pdf_sti
        except ImportError:
            logger.warning("PyMuPDF (fitz) ikke tilgjengelig — kan ikke rendre "
                           "PDF-side %d. Kvalitetsanalyse degraderer.", side_nummer)
            return None, None
        except Exception as exc:
            logger.warning("Kunne ikke rendre side %d av %s: %s",
                           side_nummer, fil_sti, exc)
            return None, None

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
            logger.warning(
                "cv2 (opencv) ikke tilgjengelig — alle dokumenter godkjennes "
                "automatisk med score=0.8 og type=%s. "
                "Installer opencv-python-headless for korrekt klassifisering.", TRYKT
            )
            return 0.8, TRYKT

    def _klassifiser(self, bilde) -> str:
        import cv2
        import numpy as np

        _, binær = cv2.threshold(bilde, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        hvit_andel = np.sum(binær == 255) / binær.size

        # Detekter tabeller via horisontale og vertikale linjer
        kanter = cv2.Canny(bilde, 50, 150)
        horisontale = cv2.morphologyEx(
            kanter,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1)),
        )
        vertikale = cv2.morphologyEx(
            kanter,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40)),
        )
        linje_andel = (np.sum(horisontale > 0) + np.sum(vertikale > 0)) / max(bilde.size, 1)
        if linje_andel > 0.01 and hvit_andel > 0.70:
            return TABELL

        if hvit_andel > 0.90:
            return TRYKT
        elif hvit_andel > 0.70:
            return BLANDET
        else:
            return HANDSKRIFT


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    PreprocessingWorker().run()
