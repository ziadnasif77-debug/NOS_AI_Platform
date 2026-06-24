"""
Opplastings-ruter (V2.1)
POST /last-opp/ — idempotens-sjekk → Postgres UPLOADED → Redis preprocess-kø → QUEUED
GET  /jobb/{job_id}   — status fra Postgres
GET  /resultat/{job_id} — resultat fra Postgres
GET  /audit/{job_id}    — audit-logg fra Postgres
"""
import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path

import psycopg2
import psycopg2.extras
import redis
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

ruter = APIRouter(tags=["opplasting"])

INNTAK_STI = os.environ.get("INNTAK_STI", "/data/inntak")


def _pg():
    from config.config_loader import CONFIG
    return psycopg2.connect(CONFIG["postgres"]["url"])


def _redis_client():
    from config.config_loader import CONFIG
    return redis.from_url(CONFIG["redis"]["url"])


def _idempotens_nokkel(innhold: bytes) -> str:
    tidsbøtte = int(time.time() / 300)
    return hashlib.sha256(innhold + str(tidsbøtte).encode()).hexdigest()


# ------------------------------------------------------------------ #
#  POST /last-opp/                                                    #
# ------------------------------------------------------------------ #

@ruter.post("/last-opp/")
async def last_opp(fil: UploadFile = File(...)):
    """
    Laster opp PDF. Returnerer 202 med job_id.
    Idempotent: samme fil i samme 5-min-vindu gir samme job_id.
    """
    if not fil.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Kun PDF-filer er støttet")

    innhold = await fil.read()
    idempotens_nokkel = _idempotens_nokkel(innhold)

    try:
        pg = _pg()
        pg.autocommit = False
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT job_id, state FROM jobs WHERE idempotency_key = %s",
                (idempotens_nokkel,),
            )
            eksisterende = cur.fetchone()

        if eksisterende:
            pg.close()
            return JSONResponse(
                status_code=200,
                content={
                    "job_id": str(eksisterende["job_id"]),
                    "state": eksisterende["state"],
                    "idempotent": True,
                    "sjekk_status": f"/jobb/{eksisterende['job_id']}",
                },
            )

        job_id = str(uuid.uuid4())
        fil_sti = Path(INNTAK_STI) / f"{job_id}.pdf"
        fil_sti.parent.mkdir(parents=True, exist_ok=True)
        with open(fil_sti, "wb") as f:
            f.write(innhold)

        with pg.cursor() as cur:
            cur.execute(
                """
                INSERT INTO jobs (job_id, idempotency_key, state, filnavn, fil_sti)
                VALUES (%s, %s, 'UPLOADED', %s, %s)
                """,
                (job_id, idempotens_nokkel, fil.filename, str(fil_sti)),
            )
            cur.execute(
                """
                INSERT INTO audit_log (job_id, event_type, to_state, worker_id, details)
                VALUES (%s, 'OPPRETTET', 'UPLOADED', 'api', %s)
                """,
                (job_id, psycopg2.extras.Json({"filnavn": fil.filename})),
            )

        from config.config_loader import CONFIG
        rc = _redis_client()
        payload = json.dumps({"job_id": job_id, "fil_sti": str(fil_sti)})
        ko = CONFIG["redis"]["kooer"]["preprocess"]
        rc.rpush(ko, payload)

        with pg.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET state = 'QUEUED', oppdatert = NOW() WHERE job_id = %s",
                (job_id,),
            )
            cur.execute(
                """
                INSERT INTO audit_log (job_id, event_type, from_state, to_state, worker_id)
                VALUES (%s, 'STATE_ENDRING', 'UPLOADED', 'QUEUED', 'api')
                """,
                (job_id,),
            )
        pg.commit()
        pg.close()

        return JSONResponse(
            status_code=202,
            content={
                "job_id": job_id,
                "filnavn": fil.filename,
                "state": "QUEUED",
                "idempotent": False,
                "sjekk_status": f"/jobb/{job_id}",
            },
        )

    except Exception as feil:
        raise HTTPException(status_code=500, detail=str(feil))


# ------------------------------------------------------------------ #
#  GET /jobb/{job_id}                                                 #
# ------------------------------------------------------------------ #

@ruter.get("/jobb/{job_id}")
async def hent_jobb(job_id: str):
    try:
        pg = _pg()
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT job_id, state, filnavn, opprettet, oppdatert FROM jobs WHERE job_id = %s",
                (job_id,),
            )
            rad = cur.fetchone()
        pg.close()
        if rad is None:
            raise HTTPException(status_code=404, detail="Jobb ikke funnet")
        return dict(rad)
    except HTTPException:
        raise
    except Exception as feil:
        raise HTTPException(status_code=500, detail=str(feil))


# ------------------------------------------------------------------ #
#  GET /resultat/{job_id}                                             #
# ------------------------------------------------------------------ #

@ruter.get("/resultat/{job_id}")
async def hent_resultat(job_id: str):
    try:
        pg = _pg()
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM results WHERE job_id = %s", (job_id,))
            rad = cur.fetchone()
        pg.close()
        if rad is None:
            raise HTTPException(status_code=404, detail="Resultat ikke funnet")
        return dict(rad)
    except HTTPException:
        raise
    except Exception as feil:
        raise HTTPException(status_code=500, detail=str(feil))


# ------------------------------------------------------------------ #
#  GET /audit/{job_id}                                                #
# ------------------------------------------------------------------ #

@ruter.get("/audit/{job_id}")
async def hent_audit(job_id: str):
    try:
        pg = _pg()
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, event_type, from_state, to_state, worker_id, details, created_at
                FROM audit_log WHERE job_id = %s ORDER BY created_at
                """,
                (job_id,),
            )
            rader = cur.fetchall()
        pg.close()
        return [dict(r) for r in rader]
    except Exception as feil:
        raise HTTPException(status_code=500, detail=str(feil))
