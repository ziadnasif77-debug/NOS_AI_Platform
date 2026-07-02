"""
BaseWorker — abstrakt basisklasse for alle V2.1-workers.

Håndterer: Redis blpop, idempotens-sjekk, optimistisk låsing,
tilstandsoverganger, retry med backoff, DLQ og audit-logg.
"""
import sys
import os
import json
import time
import uuid
import logging
import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional

import redis
import psycopg2
import psycopg2.extras

sys.path.insert(0, "/app")
from config.config_loader import CONFIG
from delt.konstanter import LOVLIGE_OVERGANGER, TERMINAL_TILSTANDER
from delt import metrikker

logger = logging.getLogger(__name__)

BACKOFF = [1, 3, 10]


class UgyldigTilstandsovergang(Exception):
    pass


class BaseWorker(ABC):

    def __init__(
        self,
        worker_id: str,
        queue_name: str,
        dlq_name: str,
        running_state: str,
        done_state: str,
    ):
        self.worker_id = worker_id
        self.queue_name = queue_name
        self.dlq_name = dlq_name
        self.running_state = running_state
        self.done_state = done_state
        self._redis = redis.from_url(CONFIG["redis"]["url"])
        self._pg_url = CONFIG["postgres"]["url"]

    # ------------------------------------------------------------------ #
    #  Hoved-løkke                                                         #
    # ------------------------------------------------------------------ #

    def run(self):
        logger.info("%s starter, lytter på %s", self.worker_id, self.queue_name)
        metrikker.start_metrikk_server()
        while True:
            try:
                raw = self._redis.blpop(self.queue_name, timeout=5)
                if raw is None:
                    continue
                _, payload = raw
                job = json.loads(payload)
                self._behandle(job)
            except Exception as exc:
                logger.exception("Uventet feil i %s: %s", self.worker_id, exc)
                time.sleep(1)

    def _behandle(self, job: dict):
        job_id = job["job_id"]
        start_tid = time.monotonic()
        with psycopg2.connect(self._pg_url) as pg:
            pg.autocommit = False
            try:
                if not self._las_jobb(job_id, pg):
                    logger.debug("Jobb %s allerede låst — hopper over", job_id)
                    return

                self._oppdater_state(job_id, self.running_state, pg)
                pg.commit()

                resultat = self.process(job, pg)

                with psycopg2.connect(self._pg_url) as pg2:
                    pg2.autocommit = False
                    self._lagre_resultat(job_id, resultat, pg2)
                    self._oppdater_state(job_id, self.done_state, pg2)
                    self._frigi_las(job_id, pg2)
                    pg2.commit()

                self._legg_i_neste_ko(job, resultat)
                self._audit(job_id, "FERDIG", from_state=self.running_state,
                            to_state=self.done_state)
                metrikker.tell_jobb(self.queue_name, "ok")
                metrikker.observer_jobb_varighet(
                    self.queue_name, time.monotonic() - start_tid
                )

            except UgyldigTilstandsovergang as exc:
                pg.rollback()
                logger.warning("Ugyldig tilstandsovergang for %s: %s", job_id, exc)
                metrikker.tell_jobb(self.queue_name, "hoppet_over")
            except Exception as exc:
                pg.rollback()
                try:
                    pg_feil = psycopg2.connect(self._pg_url)
                except Exception as tilkobling_exc:
                    logger.error(
                        "Kunne ikke opprette DB-tilkobling for feilhåndtering "
                        "job_id=%s — jobb blir gjenopprettet av reconciliation: %s",
                        job_id, tilkobling_exc,
                    )
                    return
                try:
                    self._haandter_feil(job, exc, pg_feil)
                finally:
                    pg_feil.close()

    # ------------------------------------------------------------------ #
    #  Låsing                                                              #
    # ------------------------------------------------------------------ #

    def _las_jobb(self, job_id: str, pg) -> bool:
        timeout = CONFIG["reconciliation"]["lock_timeout_sekunder"]
        expiry = datetime.utcnow() + timedelta(seconds=timeout)
        with pg.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs SET locked_by = %s, lock_expiry = %s
                WHERE job_id = %s
                  AND (locked_by IS NULL OR lock_expiry < NOW())
                """,
                (self.worker_id, expiry, job_id),
            )
            return cur.rowcount == 1

    def _frigi_las(self, job_id: str, pg):
        with pg.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET locked_by = NULL, lock_expiry = NULL WHERE job_id = %s",
                (job_id,),
            )

    # ------------------------------------------------------------------ #
    #  Tilstandsmaskin                                                     #
    # ------------------------------------------------------------------ #

    def _oppdater_state(self, job_id: str, ny_tilstand: str, pg):
        with pg.cursor() as cur:
            cur.execute("SELECT state FROM jobs WHERE job_id = %s FOR UPDATE", (job_id,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Jobb {job_id} finnes ikke")
            gjeldende = row[0]
            if (gjeldende, ny_tilstand) not in LOVLIGE_OVERGANGER:
                raise UgyldigTilstandsovergang(
                    f"{gjeldende} → {ny_tilstand} er ikke tillatt"
                )
            cur.execute(
                "UPDATE jobs SET state = %s, updated_at = NOW() WHERE job_id = %s",
                (ny_tilstand, job_id),
            )
            self._audit(job_id, "STATE_ENDRING", from_state=gjeldende,
                        to_state=ny_tilstand, pg=pg)

    # ------------------------------------------------------------------ #
    #  Resultater                                                          #
    # ------------------------------------------------------------------ #

    def _lagre_resultat(self, job_id: str, resultat: dict, pg):
        kolonne_map = {
            "PREPROCESSING":   "preprocess_result",
            "OCR_PROCESSING":  "ocr_result",
            "NLP_PROCESSING":  "nlp_result",
            "VALIDATION":      "validation_result",
        }
        kolonne = kolonne_map.get(self.running_state)
        if kolonne is None:
            return
        with pg.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO results (job_id, {kolonne})
                VALUES (%s, %s)
                ON CONFLICT (job_id) DO UPDATE SET {kolonne} = EXCLUDED.{kolonne}
                """,
                (job_id, psycopg2.extras.Json(resultat)),
            )

    # ------------------------------------------------------------------ #
    #  Neste kø                                                            #
    # ------------------------------------------------------------------ #

    def _legg_i_neste_ko(self, job: dict, resultat: dict):
        neste_ko_map = {
            "OCR_PROCESSING": CONFIG["redis"]["kooer"]["ocr"],
            "NLP_PROCESSING": CONFIG["redis"]["kooer"]["nlp"],
            "ROUTING":        CONFIG["redis"]["kooer"]["routing"],
            # VALIDATION har ingen consumer — NLPWorker bruker done_state="ROUTING"
        }
        ko = neste_ko_map.get(self.done_state)
        if ko is None:
            return
        payload = {**job, "forrige_resultat": resultat}
        self._redis.rpush(ko, json.dumps(payload))

    # ------------------------------------------------------------------ #
    #  Feilhåndtering                                                      #
    # ------------------------------------------------------------------ #

    def _haandter_feil(self, job: dict, error: Exception, pg):
        job_id = job["job_id"]
        retry_count = job.get("retry_count", 0)
        max_retries = CONFIG["redis"].get("max_retries", 3)

        if retry_count < max_retries:
            backoff = BACKOFF[min(retry_count, len(BACKOFF) - 1)]
            job["retry_count"] = retry_count + 1
            self._audit(job_id, "RETRY", details={"retry": retry_count + 1,
                                                   "feil": str(error)})
            metrikker.tell_jobb(self.queue_name, "retry")
            time.sleep(backoff)
            self._redis.rpush(self.queue_name, json.dumps(job))
        else:
            self._send_til_dlq(job, error, retry_count, pg)

    def _send_til_dlq(self, job: dict, error: Exception, retry_count: int, pg):
        job_id = job["job_id"]
        with pg.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dead_letter_queue
                  (job_id, stage, error_type, error_message, payload_snapshot, retry_count)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    job_id,
                    self.running_state,
                    type(error).__name__,
                    str(error),
                    psycopg2.extras.Json(job),
                    retry_count,
                ),
            )
            pg.commit()

        self._redis.rpush(self.dlq_name, json.dumps({
            "job_id": job_id,
            "stage": self.running_state,
            "feil": str(error),
        }))
        self._oppdater_state_direkte(job_id, "FAILED", fra_tilstand=self.running_state)
        self._audit(job_id, "DLQ", from_state=self.running_state,
                    to_state="FAILED", details={"feil": str(error), "retry_count": retry_count})
        metrikker.tell_jobb(self.queue_name, "dlq")

    def _oppdater_state_direkte(self, job_id: str, ny_tilstand: str, fra_tilstand: str = None):
        with psycopg2.connect(self._pg_url) as pg:
            with pg.cursor() as cur:
                cur.execute(
                    "UPDATE jobs SET state = %s, updated_at = NOW() WHERE job_id = %s",
                    (ny_tilstand, job_id),
                )
            pg.commit()

    # ------------------------------------------------------------------ #
    #  Audit-logg                                                          #
    # ------------------------------------------------------------------ #

    def _audit(
        self,
        job_id: str,
        event_type: str,
        from_state: Optional[str] = None,
        to_state: Optional[str] = None,
        details: Optional[dict] = None,
        pg=None,
    ):
        def _skriv(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_log (job_id, event_type, from_state, to_state,
                                          worker_id, details)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        job_id,
                        event_type,
                        from_state,
                        to_state,
                        self.worker_id,
                        psycopg2.extras.Json(details or {}),
                    ),
                )
            conn.commit()

        if pg is not None:
            try:
                _skriv(pg)
            except Exception as exc:
                logger.error(
                    "AUDIT_FEIL: kunne ikke skrive audit-record "
                    "job_id=%s event=%s — %s",
                    job_id, event_type, exc,
                )
        else:
            try:
                with psycopg2.connect(self._pg_url) as conn:
                    _skriv(conn)
            except Exception as exc:
                logger.error(
                    "AUDIT_FEIL: kunne ikke skrive audit-record "
                    "job_id=%s event=%s — %s",
                    job_id, event_type, exc,
                )

    # ------------------------------------------------------------------ #
    #  Label Studio                                                        #
    # ------------------------------------------------------------------ #

    def send_til_label_studio(
        self,
        job_id: str,
        image_path: str,
        ocr_text: str,
        project_id: int,
        stage: str,
    ):
        import requests as req

        ls_url = CONFIG["label_studio"]["url"]
        token = os.environ.get("LABEL_STUDIO_TOKEN", "")
        headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
        data = {
            "data": {
                "image": image_path,
                "text": ocr_text,
                "job_id": job_id,
                "stage": stage,
            }
        }
        try:
            req.post(
                f"{ls_url}/api/projects/{project_id}/import",
                json=[data],
                headers=headers,
                timeout=10,
            )
        except Exception as exc:
            logger.warning("Kunne ikke sende til Label Studio: %s", exc)

    # ------------------------------------------------------------------ #
    #  Abstrakt metode                                                     #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def process(self, job: dict, pg_conn) -> dict:
        """Kjør hoved-logikken. Returnerer resultat-dict."""
