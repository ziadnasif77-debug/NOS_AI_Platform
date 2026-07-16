"""
ReconciliationWorker — reparerer stuck, ghost og tapte jobber.
Kjører hvert 5. minutt og sikrer at Postgres og Redis er i sync.
"""
import sys
import json
import logging
import os
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
    # VALIDATION er hoppet over av NLPWorker — sett tilbake til nlp-kø
    "VALIDATION":     "nlp",
    "ROUTING":        "routing",
}

# Hvilken results-kolonne inneholder forrige_resultat for en gitt tilstand.
# QUEUED/PREPROCESSING har ingen forrige worker — payload trenger bare fil_sti.
STATE_TIL_RESULTAT_KOLONNE = {
    "OCR_PROCESSING": "preprocess_result",
    "NLP_PROCESSING": "ocr_result",
    "VALIDATION":     "ocr_result",
    "ROUTING":        "nlp_result",
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
            ls = self.ettersend_label_studio(pg)
            if stuck + ghost + tapte + ls > 0:
                logger.info(
                    "Reconciliation: %d stuck, %d ghost, %d tapte, "
                    "%d LS-ettersendt",
                    stuck, ghost, tapte, ls,
                )

    # ------------------------------------------------------------------ #
    #  Label Studio-etterslep                                              #
    # ------------------------------------------------------------------ #

    def ettersend_label_studio(self, pg) -> int:
        """
        REVIEW/REJECTED-beslutninger uten LABEL_STUDIO_SENDT-kvittering
        i audit_log etter-sendes til gjennomgangs-UI-et. Beslutningen
        selv ligger trygt i Postgres uansett — dette sikrer at en feilet
        best-effort-sending betyr «forsinket gjennomgang», aldri
        «usynlig gjennomgang».
        """
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                -- a) Feilede sendinger fra ALLE stadier (bildekvalitet,
                --    OCR-konfidens, validering, routing) — drevet av
                --    LABEL_STUDIO_FEILET uten senere SENDT-kvittering.
                --    Nyeste feil per jobb = endelig beslutningsprosjekt.
                (SELECT DISTINCT ON (a.job_id)
                       a.job_id,
                       (a.details->>'project_id')::int AS label_studio_project,
                       a.details->>'stage'             AS stage,
                       j.file_path,
                       COALESCE(r.ocr_result->>'text', '') AS tekst
                FROM audit_log a
                JOIN jobs j ON j.job_id = a.job_id
                LEFT JOIN results r ON r.job_id = a.job_id
                WHERE a.event_type = 'LABEL_STUDIO_FEILET'
                  AND NOT EXISTS (
                        SELECT 1 FROM audit_log s
                        WHERE s.job_id = a.job_id
                          AND s.event_type = 'LABEL_STUDIO_SENDT'
                          AND s.id > a.id)
                ORDER BY a.job_id, a.id DESC)

                UNION

                -- b) REVIEW/REJECTED-beslutninger helt uten LS-audit
                --    (historiske rader fra før kvitteringene fantes)
                SELECT r.job_id, r.label_studio_project,
                       'ettersending' AS stage, j.file_path,
                       COALESCE(r.ocr_result->>'text', '') AS tekst
                FROM results r
                JOIN jobs j ON j.job_id = r.job_id
                WHERE r.routing_decision IN ('REVIEW', 'REJECTED')
                  AND r.label_studio_project IS NOT NULL
                  AND NOT EXISTS (
                        SELECT 1 FROM audit_log a
                        WHERE a.job_id = r.job_id
                          AND a.event_type IN ('LABEL_STUDIO_SENDT',
                                               'LABEL_STUDIO_FEILET'))
                LIMIT 50
                """
            )
            rader = cur.fetchall()

        antall = 0
        for rad in rader:
            try:
                import requests as req
                ls_url = CONFIG["label_studio"]["url"]
                token = (os.environ.get("LABEL_STUDIO_API_KEY")
                         or os.environ.get("LABEL_STUDIO_TOKEN", ""))
                svar = req.post(
                    f"{ls_url}/api/projects/{rad['label_studio_project']}/import",
                    json=[{"data": {
                        "image": rad["file_path"] or "",
                        "text": rad["tekst"][:10000],
                        "job_id": str(rad["job_id"]),
                        "stage": rad["stage"] or "ettersending",
                    }}],
                    headers={"Authorization": f"Token {token}",
                             "Content-Type": "application/json"},
                    timeout=10,
                )
                svar.raise_for_status()
                with pg.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO audit_log (job_id, event_type, worker_id, details)
                        VALUES (%s, 'LABEL_STUDIO_SENDT', 'reconciliation', %s)
                        """,
                        (str(rad["job_id"]), psycopg2.extras.Json({
                            "project_id": rad["label_studio_project"],
                            "stage": rad["stage"] or "ettersending",
                            "ettersending": True,
                        })),
                    )
                pg.commit()
                antall += 1
            except Exception as exc:
                logger.warning("LS-ettersending feilet for %s: %s — "
                               "resten venter til neste runde",
                               rad["job_id"], exc)
                break   # LS er trolig nede — ikke hamre videre
        return antall

    # ------------------------------------------------------------------ #
    #  Stuck jobs (lås utløpt)                                            #
    # ------------------------------------------------------------------ #

    def reparer_stuck_jobs(self, pg) -> int:
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT job_id, state, file_path, attempt_count
                FROM jobs
                WHERE locked_by IS NOT NULL
                  AND lock_expiry < NOW()
                  AND state NOT IN ('DONE', 'FAILED')
                """
            )
            rader = cur.fetchall()

        for rad in rader:
            self._frigi_og_re_koe_atomisk(
                rad["job_id"], rad["state"], rad.get("file_path"), pg,
                audit_event="RECONCILIATION_STUCK",
                attempt_count=rad.get("attempt_count") or 0,
            )

        return len(rader)

    # ------------------------------------------------------------------ #
    #  Ghost states (aktiv i Postgres, ikke i Redis)                      #
    # ------------------------------------------------------------------ #

    def reparer_ghost_states(self, pg) -> int:
        grense = datetime.utcnow() - timedelta(minutes=self._ghost_timeout)
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT job_id, state, file_path, attempt_count
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
                self._frigi_og_re_koe_atomisk(
                    rad["job_id"], rad["state"], rad.get("file_path"), pg,
                    audit_event="RECONCILIATION_GHOST",
                    attempt_count=rad.get("attempt_count") or 0,
                )
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
                SELECT job_id, file_path, attempt_count
                FROM jobs
                WHERE state = 'UPLOADED'
                  AND created_at < %s
                """,
                (grense,),
            )
            rader = cur.fetchall()

        for rad in rader:
            job_id = rad["job_id"]
            fil_sti = rad.get("file_path", "")
            ko_nokkel = CONFIG["redis"]["kooer"]["preprocess"]
            payload = {"job_id": str(job_id), "fil_sti": fil_sti,
                       "retry_count": rad.get("attempt_count") or 0}

            # Atomisk: state-oppdatering + audit i én transaksjon
            with pg.cursor() as cur:
                cur.execute(
                    "UPDATE jobs SET state = 'QUEUED', updated_at = NOW() WHERE job_id = %s",
                    (job_id,),
                )
                cur.execute(
                    """
                    INSERT INTO audit_log (job_id, event_type, worker_id, details)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (str(job_id), "RECONCILIATION_TAPT", "reconciliation",
                     psycopg2.extras.Json({})),
                )
            pg.commit()
            # Videresending etter commit — ghost detector gjenoppretter ved neste runde hvis dette feiler
            self._send_videre(job_id, ko_nokkel, payload)

        return len(rader)

    # ------------------------------------------------------------------ #
    #  Hjelpemetoder                                                       #
    # ------------------------------------------------------------------ #

    def _frigi_og_re_koe_atomisk(self, job_id, state, file_path, pg,
                                 audit_event: str, attempt_count: int = 0):
        """
        Unlock + audit-insert i én Postgres-transaksjon, deretter Redis-push.

        Garanterer at audit-record alltid finnes hvis unlock ble gjort.
        Redis-push skjer etter commit — ved Redis-feil vil ghost-detektoren
        gjenopprette jobben ved neste runde.
        """
        ko_navn = STATE_TIL_KO.get(state)
        if ko_navn is None:
            return

        ko_nokkel = CONFIG["redis"]["kooer"][ko_navn]
        forrige = self._hent_forrige_resultat(job_id, state, pg)

        kolonne = STATE_TIL_RESULTAT_KOLONNE.get(state)
        if kolonne is not None and forrige is None:
            logger.error(
                "DATA_INKONSISTENS: job_id=%s i tilstand %s mangler %s — merker som FAILED",
                job_id, state, kolonne,
            )
            self._merk_som_feilet(job_id, state, pg)
            with pg.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_log (job_id, event_type, worker_id, details)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (str(job_id), "DATA_INKONSISTENS", "reconciliation",
                     psycopg2.extras.Json({"state": state, "mangler": kolonne})),
                )
            pg.commit()
            return

        # Atomisk: unlock + updated_at-refresh + audit i én transaksjon.
        # updated_at settes til NOW() slik at ghost-detektoren ikke matcher
        # den samme jobben igjen i samme reconciliation-runde.
        with pg.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET locked_by = NULL, lock_expiry = NULL, updated_at = NOW()
                WHERE job_id = %s
                """,
                (job_id,),
            )
            cur.execute(
                """
                INSERT INTO audit_log (job_id, event_type, worker_id, details)
                VALUES (%s, %s, %s, %s)
                """,
                (str(job_id), audit_event, "reconciliation",
                 psycopg2.extras.Json({"state": state})),
            )
        pg.commit()

        # Videresending etter vellykket commit. retry_count settes fra
        # varig attempt_count slik at giftige jobber når DLQ selv om
        # payload-telleren gikk tapt (C1-fiksen).
        p = {"job_id": str(job_id), "fil_sti": file_path or "",
             "retry_count": attempt_count}
        if forrige is not None:
            p["forrige_resultat"] = forrige
        self._send_videre(job_id, ko_nokkel, p)

    def _send_videre(self, job_id, ko_nokkel, payload: dict):
        """
        Videresender en reparert jobb. I redis-modus: rpush til køen.
        I kubeflow-modus: start en ny pipeline-run — stegene er idempotente
        (fullførte steg hopper over via tilstandsmaskinen), så en full
        re-kjøring fra preprocess er trygg uansett hvor jobben stoppet.
        """
        import os as _os
        if _os.environ.get("KJOREMODUS", "redis") == "kubeflow":
            try:
                import kfp
                endepunkt = _os.environ.get("KFP_ENDPOINT", "http://ml-pipeline:8888")
                sti = _os.environ.get("KFP_PIPELINE_STI",
                                      "/app/kubeflow/dokument_pipeline.yaml")
                kfp.Client(host=endepunkt).create_run_from_pipeline_package(
                    sti,
                    arguments={"job_id": str(job_id)},
                    run_name=f"recon-{str(job_id)[:8]}",
                    enable_caching=False,
                )
                return
            except Exception as exc:
                logger.error(
                    "KFP-gjenoppretting feilet for %s: %s — faller tilbake til Redis-kø",
                    job_id, exc,
                )
        self._redis.rpush(ko_nokkel, json.dumps(payload))

    def _re_koe(self, job_id, file_path, state, ko_nokkel, pg=None):
        forrige = self._hent_forrige_resultat(job_id, state, pg) if pg else None

        # Manglende forrige_resultat for tilstander som krever det er en
        # datainkonsistens — re-queue vil bare føre til DLQ.
        kolonne = STATE_TIL_RESULTAT_KOLONNE.get(state)
        if kolonne is not None and forrige is None:
            logger.error(
                "DATA_INKONSISTENS: job_id=%s i tilstand %s mangler %s — merker som FAILED",
                job_id, state, kolonne,
            )
            self._merk_som_feilet(job_id, state, pg)
            if pg:
                self._audit(job_id, "DATA_INKONSISTENS", pg,
                            details={"state": state, "mangler": kolonne})
            return

        p = {
            "job_id": str(job_id),
            "fil_sti": file_path or "",
        }
        if forrige is not None:
            p["forrige_resultat"] = forrige

        self._redis.rpush(ko_nokkel, json.dumps(p))

    def _hent_forrige_resultat(self, job_id, state, pg):
        """Henter forrige workers resultat fra Postgres results-tabell."""
        kolonne = STATE_TIL_RESULTAT_KOLONNE.get(state)
        if kolonne is None or pg is None:
            return None
        try:
            with pg.cursor() as cur:
                cur.execute(
                    f"SELECT {kolonne} FROM results WHERE job_id = %s",
                    (str(job_id),),
                )
                rad = cur.fetchone()
            if rad is None or rad[0] is None:
                return None
            return rad[0] if isinstance(rad[0], dict) else None
        except Exception as exc:
            logger.warning("Kunne ikke hente %s for job_id=%s: %s", kolonne, job_id, exc)
            return None

    def _merk_som_feilet(self, job_id, state, pg):
        """Setter job til FAILED ved uopprettelig datainkonsistens."""
        try:
            if pg:
                with pg.cursor() as cur:
                    cur.execute(
                        "UPDATE jobs SET state = 'FAILED', updated_at = NOW() WHERE job_id = %s",
                        (str(job_id),),
                    )
                pg.commit()
            with psycopg2.connect(self._pg_url) as pg2:
                with pg2.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO dead_letter_queue
                          (job_id, stage, error_type, error_message, payload_snapshot, retry_count)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            str(job_id),
                            state,
                            "DataInkonsistens",
                            f"Mangler forrige_resultat for tilstand {state}",
                            psycopg2.extras.Json({"job_id": str(job_id), "state": state}),
                            0,
                        ),
                    )
                pg2.commit()
        except Exception as exc:
            logger.error("Kunne ikke merke job_id=%s som FAILED: %s", job_id, exc)

    def _er_i_redis(self, job_id: str, ko_nokkel: str) -> bool:
        try:
            elementer = self._redis.lrange(ko_nokkel, 0, -1)
            jid = str(job_id)
            for e in elementer:
                try:
                    payload = json.loads(e)
                    if payload.get("job_id") == jid:
                        return True
                except (json.JSONDecodeError, AttributeError):
                    continue
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
