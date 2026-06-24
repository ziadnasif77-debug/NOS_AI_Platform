"""
Lag 3 — Routing Worker
Bestemmer APPROVED / REVIEW / REJECTED basert på alle tidligere lag.
"""
import sys
import os
import json
import logging
import socket

import psycopg2
import psycopg2.extras

sys.path.insert(0, "/app")
from config.config_loader import CONFIG
from tjenester.workers.base_worker import BaseWorker

logger = logging.getLogger(__name__)

WORKER_ID = f"lag3-{socket.gethostname()}"


class RoutingWorker(BaseWorker):

    def __init__(self):
        cfg = CONFIG["redis"]
        super().__init__(
            worker_id=WORKER_ID,
            queue_name=cfg["kooer"]["routing"],
            dlq_name=cfg["dlq"]["validation"],
            running_state="ROUTING",
            done_state="DONE",
        )

    def process(self, job: dict, pg_conn) -> dict:
        job_id = job["job_id"]

        nlp_res = job.get("forrige_resultat", {})
        ocr_konfidens = job.get("ocr_konfidens", 1.0)
        nlp_konfidens = nlp_res.get("nlp_confidence", 1.0)
        validering = nlp_res.get("validation", {"gyldig": True, "feil": []})
        anomali = nlp_res.get("anomaly", {"har_anomali": False})

        beslutning, grunn, ls_project = self._bestem_beslutning(
            ocr_konfidens, nlp_konfidens, validering, anomali
        )

        audit_trail = [
            f"ocr_konfidens={ocr_konfidens:.2f}",
            f"nlp_konfidens={nlp_konfidens:.2f}",
            f"validering_gyldig={validering['gyldig']}",
            f"har_anomali={anomali.get('har_anomali', False)}",
            f"beslutning={beslutning}",
            f"grunn={grunn}",
        ]

        self._lagre_routing_beslutning(job_id, beslutning, ls_project, pg_conn)

        if beslutning == "APPROVED":
            self._send_til_milvus(job_id, nlp_res)
        elif beslutning in ("REVIEW", "REJECTED") and ls_project:
            self.send_til_label_studio(
                job_id=job_id,
                image_path=job.get("fil_sti", ""),
                ocr_text=nlp_res.get("summary", ""),
                project_id=ls_project,
                stage=grunn,
            )

        return {
            "job_id": job_id,
            "decision": beslutning,
            "label_studio_project": ls_project,
            "reason": grunn,
            "audit_trail": audit_trail,
        }

    def _bestem_beslutning(
        self,
        ocr_konfidens: float,
        nlp_konfidens: float,
        validering: dict,
        anomali: dict,
    ) -> tuple:
        ocr_terskel = CONFIG["terskler"]["ocr_konfidens"] / 100.0
        nlp_terskel = CONFIG["terskler"]["nlp_konfidens"] / 100.0

        ls_prosjekter = CONFIG["label_studio"]["prosjekter"]

        if ocr_konfidens < ocr_terskel:
            return "REVIEW", "lav_ocr_konfidens", ls_prosjekter["lag2"]

        if nlp_konfidens < nlp_terskel:
            return "REVIEW", "lav_nlp_konfidens", ls_prosjekter["lag3"]

        if not validering.get("gyldig", True):
            return "REVIEW", "valideringsfeil", ls_prosjekter["lag4"]

        if anomali.get("har_anomali", False):
            return "REVIEW", "anomali_detektert", ls_prosjekter["lag4"]

        return "APPROVED", "alle_lag_godkjent", None

    def _lagre_routing_beslutning(
        self, job_id: str, beslutning: str, ls_project, pg
    ):
        with pg.cursor() as cur:
            cur.execute(
                """
                INSERT INTO results (job_id, routing_decision, label_studio_project)
                VALUES (%s, %s, %s)
                ON CONFLICT (job_id) DO UPDATE
                  SET routing_decision      = EXCLUDED.routing_decision,
                      label_studio_project  = EXCLUDED.label_studio_project
                """,
                (job_id, beslutning, ls_project),
            )

    def _send_til_milvus(self, job_id: str, nlp_res: dict):
        try:
            import redis as r

            rc = r.from_url(CONFIG["redis"]["url"])
            rc.rpush("queue:sok_indeksering", json.dumps({
                "job_id": job_id,
                "entities": nlp_res.get("entities", {}),
                "summary": nlp_res.get("summary", ""),
                "document_class": nlp_res.get("document_class", ""),
            }))
        except Exception as exc:
            logger.warning("Kunne ikke sende til Milvus-kø: %s", exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    RoutingWorker().run()
