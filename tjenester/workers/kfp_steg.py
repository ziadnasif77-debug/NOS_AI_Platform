"""
KFP-stegkjører — kjører ETT pipeline-steg for ÉN jobb (kubeflow-modus).

I kubeflow-modus erstattes Redis-køene av Kubeflow Pipelines:
API-et starter én pipeline-run per dokument, og hvert steg i kjøringen
starter denne modulen inne i riktig worker-image. Postgres forblir
eneste kilde til sannhet — tilstand og resultater leses og skrives der,
aldri via kø. Retry håndteres ikke av kø i denne modusen: feiler et
steg, går jobben rett til DLQ og KFP markerer kjøringen som feilet.

Bruk: python -m tjenester.workers.kfp_steg --steg ocr --job-id <uuid>
"""
import sys
import argparse
import importlib
import logging

import psycopg2
import psycopg2.extras

sys.path.insert(0, "/app")
from tjenester.workers.base_worker import UgyldigTilstandsovergang

logger = logging.getLogger(__name__)

# steg → (modul, klasse, results-kolonne med forrige stegs resultat)
STEG_MAP = {
    "preprocess": ("tjenester.workers.lag0_preprocessing.lag0", "PreprocessingWorker", None),
    "ocr":        ("tjenester.workers.lag1_ocr.lag1",           "OCRWorker",           "preprocess_result"),
    "nlp":        ("tjenester.workers.lag2_nlp.lag2",           "NLPWorker",           "ocr_result"),
    "routing":    ("tjenester.workers.lag3_routing.lag3",       "RoutingWorker",       "nlp_result"),
}


def _hent_jobb(job_id: str, forrige_kolonne, pg_url: str) -> dict:
    """Bygger job-dict fra Postgres — erstatter kø-payloaden i redis-modus."""
    with psycopg2.connect(pg_url) as pg:
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT file_path FROM jobs WHERE job_id = %s", (job_id,))
            rad = cur.fetchone()
            if rad is None:
                raise ValueError(f"Jobb {job_id} finnes ikke i Postgres")
            job = {"job_id": job_id, "fil_sti": rad["file_path"]}
            if forrige_kolonne:
                cur.execute(
                    f"SELECT {forrige_kolonne} FROM results WHERE job_id = %s",
                    (job_id,),
                )
                res = cur.fetchone()
                if res is None or res[forrige_kolonne] is None:
                    raise ValueError(
                        f"Forrige resultat ({forrige_kolonne}) mangler for {job_id}"
                    )
                job["forrige_resultat"] = res[forrige_kolonne]
    return job


def kjor_steg(steg: str, job_id: str):
    modulnavn, klassenavn, forrige_kolonne = STEG_MAP[steg]
    modul = importlib.import_module(modulnavn)
    worker = getattr(modul, klassenavn)()

    job = _hent_jobb(job_id, forrige_kolonne, worker._pg_url)

    pg = psycopg2.connect(worker._pg_url)
    pg.autocommit = False
    try:
        if not worker._las_jobb(job_id, pg):
            raise RuntimeError(f"Jobb {job_id} er låst av en annen prosess")

        worker._oppdater_state(job_id, worker.running_state, pg)
        pg.commit()

        resultat = worker.process(job, pg)

        with psycopg2.connect(worker._pg_url) as pg2:
            pg2.autocommit = False
            worker._lagre_resultat(job_id, resultat, pg2)
            worker._oppdater_state(job_id, worker.done_state, pg2)
            worker._frigi_las(job_id, pg2)
            pg2.commit()

        worker._audit(job_id, "FERDIG", from_state=worker.running_state,
                      to_state=worker.done_state)
        logger.info("Steg %s fullført for job_id=%s", steg, job_id)

    except UgyldigTilstandsovergang as exc:
        # Typisk en re-kjøring av et allerede fullført steg — ufarlig.
        pg.rollback()
        logger.warning("Ugyldig tilstandsovergang for %s: %s — hopper over", job_id, exc)
    except Exception as exc:
        pg.rollback()
        try:
            worker._send_til_dlq(job, exc, retry_count=0, pg=pg)
        except Exception as dlq_exc:
            logger.error("Kunne ikke skrive til DLQ for %s: %s", job_id, dlq_exc)
        raise
    finally:
        pg.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Kjør ett pipeline-steg (kubeflow-modus)")
    parser.add_argument("--steg", required=True, choices=sorted(STEG_MAP))
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    kjor_steg(args.steg, args.job_id)
