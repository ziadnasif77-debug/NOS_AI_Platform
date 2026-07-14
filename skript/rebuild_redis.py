"""
Rebuilder Redis-køer fra Postgres.
Kjøres ved Redis-restart eller desync.
Postgres er sannheten — Redis rebuildes fra den.

Payload-kontrakten er identisk med reconciliation-workerens:
  {job_id, fil_sti, retry_count[, forrige_resultat]}
Jobber i tilstander som krever forrige_resultat men mangler det i
results-tabellen, markeres FAILED (DATA_INKONSISTENS) i stedet for å
re-køes til en garantert DLQ-løkke.
"""
import os, sys, json, logging
sys.path.insert(0, ".")
from config.config_loader import CONFIG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rebuild_redis")

POSTGRES_URL = os.environ.get("POSTGRES_URL", CONFIG["postgres"]["url"])
REDIS_URL = os.environ.get("REDIS_URL", CONFIG["redis"]["url"])

STATE_TIL_KO = {
    "UPLOADED":       CONFIG["redis"]["kooer"]["preprocess"],
    "QUEUED":         CONFIG["redis"]["kooer"]["preprocess"],
    "PREPROCESSING":  CONFIG["redis"]["kooer"]["preprocess"],
    "OCR_PROCESSING": CONFIG["redis"]["kooer"]["ocr"],
    "NLP_PROCESSING": CONFIG["redis"]["kooer"]["nlp"],
    # VALIDATION hoppes over av NLPWorker (validering skjer inline) —
    # jobs som sitter fast i VALIDATION skal tilbake til nlp-køen
    "VALIDATION":     CONFIG["redis"]["kooer"]["nlp"],
    "ROUTING":        CONFIG["redis"]["kooer"]["routing"],
}

# Hvilken results-kolonne som er forrige_resultat for en gitt tilstand
STATE_TIL_RESULTAT_KOLONNE = {
    "OCR_PROCESSING": "preprocess_result",
    "NLP_PROCESSING": "ocr_result",
    "VALIDATION":     "ocr_result",
    "ROUTING":        "nlp_result",
}


def rebuild():
    import psycopg2, psycopg2.extras, redis as redis_lib
    pg = psycopg2.connect(POSTGRES_URL)
    r = redis_lib.from_url(REDIS_URL, decode_responses=True)
    cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT j.job_id, j.state, j.file_path, j.attempt_count,
               r.preprocess_result, r.ocr_result, r.nlp_result
        FROM jobs j
        LEFT JOIN results r ON r.job_id = j.job_id
        WHERE j.state NOT IN ('DONE', 'FAILED')
        AND (j.lock_expiry IS NULL OR j.lock_expiry < NOW())
    """)
    rader = cur.fetchall()

    antall, inkonsistente = 0, 0
    for rad in rader:
        state = rad["state"]
        ko = STATE_TIL_KO.get(state)
        if not ko:
            continue

        payload = {
            "job_id": str(rad["job_id"]),
            "fil_sti": rad["file_path"] or "",
            "retry_count": rad["attempt_count"] or 0,
        }

        kolonne = STATE_TIL_RESULTAT_KOLONNE.get(state)
        if kolonne is not None:
            forrige = rad.get(kolonne)
            if not isinstance(forrige, dict):
                logger.error(
                    "DATA_INKONSISTENS: %s i %s mangler %s — markeres FAILED",
                    rad["job_id"], state, kolonne,
                )
                with pg.cursor() as feilkur:
                    feilkur.execute(
                        "UPDATE jobs SET state = 'FAILED', updated_at = NOW(), "
                        "completed_at = NOW() WHERE job_id = %s",
                        (str(rad["job_id"]),),
                    )
                    feilkur.execute(
                        """
                        INSERT INTO audit_log (job_id, event_type, worker_id, details)
                        VALUES (%s, 'DATA_INKONSISTENS', 'rebuild_redis', %s)
                        """,
                        (str(rad["job_id"]),
                         psycopg2.extras.Json({"state": state, "mangler": kolonne})),
                    )
                pg.commit()
                inkonsistente += 1
                continue
            payload["forrige_resultat"] = forrige

        r.rpush(ko, json.dumps(payload))
        antall += 1

    cur.close()
    pg.close()
    logger.info("Rebuilt %d jobber fra Postgres til Redis (%d inkonsistente markert FAILED)",
                antall, inkonsistente)


if __name__ == "__main__":
    rebuild()
