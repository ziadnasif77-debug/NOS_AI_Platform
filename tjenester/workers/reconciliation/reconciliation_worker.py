"""
ReconciliationWorker — reparerer stuck, ghost og tapte jobber.
Kjører hvert 5. minutt og sikrer at Postgres og Redis er i sync.
"""
import sys
import json
import logging
import time
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras
import redis

sys.path.insert(0, "/app")
from config.config_loader import CONFIG

logger = logging.getLogger(__name__)

STATE_TIL_KO = {
    "QUEUED":         "preprocess",
    "PREPROCESSING":  "preprocess",
    "OCR_PROCESSING": "ocr",
    "NLP_PROCESSING": "nlp",
    "VALIDATION":     "validation",
    "ROUTING":        "routing",
}


class ReconciliationWorker:

    def __init__(self):
        self._pg_url = CONFIG["postgres"]["url"]
        self._redis = redis.from_url(CONFIG["redis"]["url"])
        self._intervall = CONFIG["reconciliation"]["intervall_sekunder"]
        self._lock_timeout = CONFIG["reconciliation"]["lock_timeout_sekunder"]
        self._ghost_timeout = CONFIG["reconciliation"]["ghost_timeout_minutter"]

    def run(self):
        logger.info("ReconciliationWorker starter (intervall=%ss)", self._intervall)
        while True:
            try:
                self._kjor_runde()
            except Exception as exc:
                logger.exception("Feil i reconciliation: %s", exc)
            time.sleep(self._intervall)

    def _kjor_runde(self):
        with psycopg2.connect(self._pg_url) as pg:
            stuck = self.reparer_stuck_jobs(pg)
            ghost = self.reparer_ghost_states(pg)
            tapte = self.reparer_tapte_jobber(pg)
            if stuck + ghost + tapte > 0:
                logger.info(
                    "Reconciliation: %d stuck, %d ghost, %d tapte reparert",
                    stuck, ghost, tapte,
                )

    # ------------------------------------------------------------------ #
    #  Stuck jobs (lås utløpt)                                            #
    # ------------------------------------------------------------------ #

    def reparer_stuck_jobs(self, pg) -> int:
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT job_id, state, file_path
                FROM jobs
                WHERE locked_by IS NOT NULL
                  AND lock_expiry < NOW()
                  AND state NOT IN ('DONE', 'FAILED')
                """
            )
            rader = cur.fetchall()

        for rad in rader:
            self._frigi_og_re_koe(rad["job_id"], rad["state"], rad.get("file_path"), pg)
            self._audit(rad["job_id"], "RECONCILIATION_STUCK", pg,
                        details={"state": rad["state"]})

        return len(rader)

    # ------------------------------------------------------------------ #
    #  Ghost states (aktiv i Postgres, ikke i Redis)                      #
    # ------------------------------------------------------------------ #

    def reparer_ghost_states(self, pg) -> int:
        grense = datetime.utcnow() - timedelta(minutes=self._ghost_timeout)
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT job_id, state, file_path
                FROM jobs
                WHERE state NOT IN ('DONE', 'FAILED', 'UPLOADED')
                  AND locked_by IS NULL
                  AND updated_at < %s
                """,
                (grense,),
            )
            rader = cur.fetchall()

        antall = 0
        for rad in rader:
            ko_navn = STATE_TIL_KO.get(rad["state"])
            if ko_navn is None:
                continue
            ko_nokkel = CONFIG["redis"]["kooer"][ko_navn]
            if not self._er_i_redis(rad["job_id"], ko_nokkel):
                self._re_koe(rad["job_id"], rad.get("file_path"), rad["state"], ko_nokkel)
                self._audit(rad["job_id"], "RECONCILIATION_GHOST", pg,
                            details={"state": rad["state"]})
                antall += 1

        return antall

    # ------------------------------------------------------------------ #
    #  Tapte jobber (UPLOADED > 5 min uten å bli QUEUED)                  #
    # ------------------------------------------------------------------ #

    def reparer_tapte_jobber(self, pg) -> int:
        grense = datetime.utcnow() - timedelta(minutes=5)
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT job_id, file_path
                FROM jobs
                WHERE state = 'UPLOADED'
                  AND created_at < %s
                """,
                (grense,),
            )
            rader = cur.fetchall()

        for rad in rader:
            with pg.cursor() as cur:
                cur.execute(
                    "UPDATE jobs SET state = 'QUEUED', updated_at = NOW() WHERE job_id = %s",
                    (rad["job_id"],),
                )
            ko_nokkel = CONFIG["redis"]["kooer"]["preprocess"]
            payload = {"job_id": str(rad["job_id"]), "fil_sti": rad.get("file_path", "")}
            self._redis.rpush(ko_nokkel, json.dumps(payload))
            self._audit(rad["job_id"], "RECONCILIATION_TAPT", pg)
            pg.commit()

        return len(rader)

    # ------------------------------------------------------------------ #
    #  Hjelpemetoder                                                       #
    # ------------------------------------------------------------------ #

    def _frigi_og_re_koe(self, job_id, state, file_path, pg):
        with pg.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET locked_by = NULL, lock_expiry = NULL WHERE job_id = %s",
                (job_id,),
            )
        pg.commit()
        ko_navn = STATE_TIL_KO.get(state)
        if ko_navn:
            ko_nokkel = CONFIG["redis"]["kooer"][ko_navn]
            self._re_koe(job_id, file_path, state, ko_nokkel)

    def _re_koe(self, job_id, file_path, state, ko_nokkel):
        p = {"job_id": str(job_id), "fil_sti": file_path or ""}
        self._redis.rpush(ko_nokkel, json.dumps(p))

    def _er_i_redis(self, job_id: str, ko_nokkel: str) -> bool:
        try:
            elementer = self._redis.lrange(ko_nokkel, 0, -1)
            for e in elementer:
                if str(job_id) in e.decode("utf-8", errors="ignore"):
                    return True
        except Exception:
            pass
        return False

    def _audit(self, job_id, event_type: str, pg, details: dict = None):
        try:
            with pg.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_log (job_id, event_type, worker_id, details)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        str(job_id),
                        event_type,
                        "reconciliation",
                        psycopg2.extras.Json(details or {}),
                    ),
                )
            pg.commit()
        except Exception as exc:
            logger.warning("Audit feilet: %s", exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ReconciliationWorker().run()
