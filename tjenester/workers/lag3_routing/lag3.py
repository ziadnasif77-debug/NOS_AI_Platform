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
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "/app")
from config.config_loader import CONFIG
from delt.skjemaer import NLPResultat
from tjenester.workers.base_worker import BaseWorker

logger = logging.getLogger(__name__)

WORKER_ID = f"lag3-{socket.gethostname()}"


class RoutingWorker(BaseWorker):

    def __init__(self):
        cfg = CONFIG["redis"]
        super().__init__(
            worker_id=WORKER_ID,
            queue_name=cfg["kooer"]["routing"],
            dlq_name=cfg["dlq"]["routing"],
            running_state="ROUTING",
            done_state="DONE",
        )

    def process(self, job: dict, pg_conn) -> dict:
        job_id = job["job_id"]

        nlp_res = NLPResultat.model_validate(job["forrige_resultat"])
        ocr_konfidens = nlp_res.ocr_confidence
        nlp_konfidens = nlp_res.nlp_confidence
        validering = nlp_res.validation
        anomali = nlp_res.anomaly

        beslutning, grunn, ls_project = self._bestem_beslutning(
            ocr_konfidens, nlp_konfidens, validering, anomali
        )

        audit_trail = [
            f"ocr_konfidens={ocr_konfidens:.2f}",
            f"nlp_konfidens={nlp_konfidens:.2f}",
            f"validering_gyldig={validering.gyldig}",
            f"har_anomali={anomali.har_anomali}",
            f"beslutning={beslutning}",
            f"grunn={grunn}",
        ]

        self._lagre_routing_beslutning(job_id, beslutning, ls_project, pg_conn)

        if beslutning == "APPROVED":
            dokument_id, side_nummer = self._hent_side_info(job_id, pg_conn)
            self._send_til_milvus(job_id, nlp_res, dokument_id, side_nummer)
        elif beslutning in ("REVIEW", "REJECTED") and ls_project:
            self.send_til_label_studio(
                job_id=job_id,
                image_path=job.get("fil_sti", ""),
                ocr_text=nlp_res.summary,
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
        validering,
        anomali,
    ) -> tuple:
        ocr_terskel = CONFIG["terskler"]["ocr_konfidens"] / 100.0
        nlp_terskel = CONFIG["terskler"]["nlp_konfidens"] / 100.0

        ls_prosjekter = CONFIG["label_studio"]["prosjekter"]

        if ocr_konfidens < ocr_terskel:
            return "REVIEW", "lav_ocr_konfidens", ls_prosjekter["ocr_konfidens"]

        if nlp_konfidens < nlp_terskel:
            return "REVIEW", "lav_nlp_konfidens", ls_prosjekter["nlp_konfidens"]

        if not validering.gyldig:
            return "REVIEW", "valideringsfeil", ls_prosjekter["validering"]

        if anomali.har_anomali:
            return "REVIEW", "anomali_detektert", ls_prosjekter["validering"]

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
        pg.commit()

    # Avgrenset pool i stedet for én tråd per dokument — hindrer
    # trådeksplosjon under last. Køen i poolen gir naturlig backpressure.
    _indekserings_pool = ThreadPoolExecutor(
        max_workers=4, thread_name_prefix="milvus-indeksering"
    )

    def _hent_side_info(self, job_id: str, pg) -> tuple:
        """dokument_id + side_nummer fra Postgres — søket grupperes på
        dokument, ikke på enkeltside-jobben."""
        try:
            with pg.cursor() as cur:
                cur.execute(
                    "SELECT dokument_id, side_nummer FROM jobs WHERE job_id = %s",
                    (job_id,),
                )
                rad = cur.fetchone()
            if rad:
                return str(rad[0] or job_id), int(rad[1] or 0)
        except Exception as exc:
            logger.warning("Kunne ikke hente side-info for %s: %s", job_id, exc)
        return job_id, 0

    def _send_til_milvus(self, job_id: str, nlp_res, dokument_id=None, side_nummer=0):
        """Milvus-indeksering i avgrenset bakgrunnspool — blokkerer ikke worker."""
        self._indekserings_pool.submit(
            self._send_til_milvus_sync, job_id, nlp_res,
            dokument_id or job_id, side_nummer,
        )

    def _send_til_milvus_sync(self, job_id: str, nlp_res, dokument_id=None, side_nummer=0):
        import requests as req
        import time as _time
        sok_url = CONFIG.get("tjenester", {}).get("sok_url", "http://sok:8003")
        entiteter = nlp_res.entities
        payload = {
            "tekst": nlp_res.summary,
            "filnavn": entiteter.get("navn", ""),
            "metadata": {
                "fil_id": dokument_id or job_id,
                "side_nummer": side_nummer,
                "navn": entiteter.get("navn", ""),
                "dato": entiteter.get("dato", ""),
                "ytelse": entiteter.get("ytelse", ""),
                "fylke": entiteter.get("fylke", ""),
                "dokumenttype": nlp_res.document_class,
            },
        }
        for forsok in range(1, 4):
            try:
                svar = req.post(f"{sok_url}/indekser", json=payload, timeout=10)
                svar.raise_for_status()
                logger.info("Milvus-indeksering fullført for job_id=%s", job_id)
                return
            except Exception as exc:
                logger.warning("Milvus-indeksering forsøk %d feilet: %s", forsok, exc)
                if forsok < 3:
                    _time.sleep(forsok * 2)
        logger.error("Milvus-indeksering feilet etter 3 forsøk for job_id=%s", job_id)
        # Varig spor: uten dette forsvinner APPROVED-dokumenter stille
        # fra søket. Audit-recorden gjør tapet synlig og re-indekserbart.
        self._audit(job_id, "INDEKSERING_FEILET",
                    details={"grunn": "milvus_utilgjengelig", "forsok": 3})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    RoutingWorker().run()
