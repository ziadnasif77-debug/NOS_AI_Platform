"""
Rebuilder Redis-køer fra Postgres.
Kjøres ved Redis-restart eller desync.
Postgres er sannheten — Redis rebuildes fra den.
"""
import os, sys, json, logging
from datetime import datetime
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

def rebuild():
    import psycopg2, redis as redis_lib
    pg = psycopg2.connect(POSTGRES_URL)
    r = redis_lib.from_url(REDIS_URL, decode_responses=True)
    cur = pg.cursor()
    cur.execute("""
        SELECT job_id, state, idempotency_key, priority
        FROM jobs
        WHERE state NOT IN ('DONE', 'FAILED')
        AND (lock_expiry IS NULL OR lock_expiry < NOW())
    """)
    rader = cur.fetchall()
    antall = 0
    for job_id, state, idempotency_key, priority in rader:
        ko = STATE_TIL_KO.get(state)
        if not ko:
            continue
        r.rpush(ko, json.dumps({
            "job_id": str(job_id),
            "idempotency_key": idempotency_key,
            "stage": state.lower(),
            "priority": priority or 1,
            "enqueued_at": datetime.now().isoformat(),
        }))
        antall += 1
    cur.close()
    pg.close()
    logger.info(f"Rebuilt {antall} jobber fra Postgres til Redis")

if __name__ == "__main__":
    rebuild()
