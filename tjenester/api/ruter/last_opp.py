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

# KJOREMODUS styrer hvordan jobber sendes videre etter opplasting:
#   redis    (standard) — rpush til queue:preprocess, workers plukker via blpop
#   kubeflow           — start én Kubeflow-pipeline-run per dokument
KJOREMODUS = os.environ.get("KJOREMODUS", "redis")
KFP_PIPELINE_STI = os.environ.get("KFP_PIPELINE_STI", "/app/kubeflow/dokument_pipeline.yaml")


def _start_kfp_kjoring(job_id: str):
    import kfp

    endepunkt = os.environ.get("KFP_ENDPOINT", "http://ml-pipeline:8888")
    klient = kfp.Client(host=endepunkt)
    klient.create_run_from_pipeline_package(
        KFP_PIPELINE_STI,
        arguments={"job_id": job_id},
        run_name=f"dokument-{job_id[:8]}",
        enable_caching=False,
    )


def _pg():
    from config.config_loader import CONFIG
    return psycopg2.connect(CONFIG["postgres"]["url"])


def _redis_client():
    from config.config_loader import CONFIG
    return redis.from_url(CONFIG["redis"]["url"])


def _idempotens_nokkel(innhold: bytes) -> str:
    tidsbøtte = int(time.time() / 300)
    return hashlib.sha256(innhold + str(tidsbøtte).encode()).hexdigest()


def _valider_job_id(job_id: str) -> str:
    """Ugyldig UUID skal gi 422 — ikke 500 fra Postgres."""
    try:
        return str(uuid.UUID(job_id))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="Ugyldig job_id — må være UUID")


def _antall_sider(innhold: bytes) -> int:
    """Teller sider i PDF-en. Kaster HTTPException 400 ved korrupt fil."""
    import fitz
    try:
        with fitz.open(stream=innhold, filetype="pdf") as dok:
            antall = dok.page_count
    except Exception:
        raise HTTPException(status_code=400, detail="Ugyldig eller korrupt PDF")
    if antall < 1:
        raise HTTPException(status_code=400, detail="PDF-en har ingen sider")
    return antall


def _idempotent_svar(pg, idempotens_nokkel: str):
    """
    Slår opp eksisterende dokument for nøkkelen og bygger 200-responsen.
    Flersidig: nøkkelen for side 0 identifiserer dokumentet; alle
    søsken-jobber hentes via dokument_id.
    """
    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT job_id, state, dokument_id, antall_sider FROM jobs "
            "WHERE idempotency_key = %s",
            (f"{idempotens_nokkel}:side0",),
        )
        rad = cur.fetchone()
        if rad is None:
            return None
        dokument_id = rad["dokument_id"] or rad["job_id"]
        cur.execute(
            "SELECT job_id FROM jobs WHERE dokument_id = %s ORDER BY side_nummer",
            (dokument_id,),
        )
        job_ids = [str(r["job_id"]) for r in cur.fetchall()] or [str(rad["job_id"])]
    return JSONResponse(
        status_code=200,
        content={
            "dokument_id": str(dokument_id),
            "job_id": job_ids[0],
            "job_ids": job_ids,
            "antall_sider": rad["antall_sider"] or len(job_ids),
            "state": rad["state"],
            "idempotent": True,
            "sjekk_status": f"/dokument/{dokument_id}/status",
        },
    )


# ------------------------------------------------------------------ #
#  POST /last-opp/                                                    #
# ------------------------------------------------------------------ #

@ruter.post("/last-opp/")
async def last_opp(fil: UploadFile = File(...)):
    """
    Laster opp PDF. Flersidig PDF splittes i ÉN jobb per side —
    hver side får full livssyklus, audit-spor og uavhengig feilhåndtering.
    Returnerer 202 med dokument_id + job_ids (job_id = første side,
    beholdt for bakoverkompatibilitet).
    Idempotent: samme fil i samme 5-min-vindu gir samme dokument.
    """
    filnavn = fil.filename or ""
    if not filnavn.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Kun PDF-filer er støttet")

    innhold = await fil.read()
    idempotens_nokkel = _idempotens_nokkel(innhold)
    antall_sider = _antall_sider(innhold)

    pg = _pg()
    fil_sti = None
    committet = False
    try:
        pg.autocommit = False

        eksisterende = _idempotent_svar(pg, idempotens_nokkel)
        if eksisterende is not None:
            return eksisterende

        dokument_id = str(uuid.uuid4())
        fil_sti = Path(INNTAK_STI) / f"{dokument_id}.pdf"
        fil_sti.parent.mkdir(parents=True, exist_ok=True)
        with open(fil_sti, "wb") as f:
            f.write(innhold)

        job_ids = []
        with pg.cursor() as cur:
            for side in range(antall_sider):
                job_id = str(uuid.uuid4())
                job_ids.append(job_id)
                cur.execute(
                    """
                    INSERT INTO jobs (job_id, idempotency_key, state, file_name,
                                      file_path, dokument_id, side_nummer, antall_sider)
                    VALUES (%s, %s, 'UPLOADED', %s, %s, %s, %s, %s)
                    """,
                    (job_id, f"{idempotens_nokkel}:side{side}", filnavn,
                     str(fil_sti), dokument_id, side, antall_sider),
                )
                cur.execute(
                    """
                    INSERT INTO audit_log (job_id, event_type, to_state, worker_id, details)
                    VALUES (%s, 'OPPRETTET', 'UPLOADED', 'api', %s)
                    """,
                    (job_id, psycopg2.extras.Json(
                        {"filnavn": filnavn, "dokument_id": dokument_id,
                         "side_nummer": side, "antall_sider": antall_sider})),
                )
                cur.execute(
                    "UPDATE jobs SET state = 'QUEUED', updated_at = NOW() WHERE job_id = %s",
                    (job_id,),
                )
                cur.execute(
                    """
                    INSERT INTO audit_log (job_id, event_type, from_state, to_state, worker_id)
                    VALUES (%s, 'STATE_ENDRING', 'UPLOADED', 'QUEUED', 'api')
                    """,
                    (job_id,),
                )
        # Commit all Postgres changes before pushing to Redis.
        # If the process crashes between commit and rpush, the ghost detector
        # will re-queue the jobs within reconciliation.ghost_timeout_minutter.
        pg.commit()
        committet = True

        if KJOREMODUS == "kubeflow":
            for job_id in job_ids:
                _start_kfp_kjoring(job_id)
        else:
            from config.config_loader import CONFIG
            rc = _redis_client()
            ko = CONFIG["redis"]["kooer"]["preprocess"]
            for side, job_id in enumerate(job_ids):
                rc.rpush(ko, json.dumps(
                    {"job_id": job_id, "fil_sti": str(fil_sti),
                     "side_nummer": side}))

        return JSONResponse(
            status_code=202,
            content={
                "dokument_id": dokument_id,
                "job_id": job_ids[0],
                "job_ids": job_ids,
                "antall_sider": antall_sider,
                "filnavn": filnavn,
                "state": "QUEUED",
                "idempotent": False,
                "sjekk_status": f"/dokument/{dokument_id}/status",
            },
        )

    except psycopg2.errors.UniqueViolation:
        # To samtidige opplastinger av samme fil: den andre taper
        # INSERT-kappløpet — svar idempotent i stedet for 500.
        pg.rollback()
        if fil_sti is not None:
            Path(fil_sti).unlink(missing_ok=True)
        svar = _idempotent_svar(pg, idempotens_nokkel)
        if svar is not None:
            return svar
        raise HTTPException(status_code=409, detail="Samtidig opplasting — prøv igjen")
    except HTTPException:
        pg.rollback()
        raise
    except Exception as feil:
        pg.rollback()
        # Rydd kun bort filen hvis jobben IKKE er committet — etter commit
        # eies filen av jobben (ghost-detektoren re-køer den).
        if fil_sti is not None and not committet:
            Path(fil_sti).unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(feil))
    finally:
        pg.close()


# ------------------------------------------------------------------ #
#  GET /jobb/{job_id}                                                 #
# ------------------------------------------------------------------ #

@ruter.get("/jobb/{job_id}")
async def hent_jobb(job_id: str):
    job_id = _valider_job_id(job_id)
    pg = _pg()
    try:
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT job_id, state, file_name, created_at, updated_at, completed_at "
                "FROM jobs WHERE job_id = %s",
                (job_id,),
            )
            rad = cur.fetchone()
        if rad is None:
            raise HTTPException(status_code=404, detail="Jobb ikke funnet")
        return dict(rad)
    except HTTPException:
        raise
    except Exception as feil:
        raise HTTPException(status_code=500, detail=str(feil))
    finally:
        pg.close()


# ------------------------------------------------------------------ #
#  GET /resultat/{job_id}                                             #
# ------------------------------------------------------------------ #

@ruter.get("/resultat/{job_id}")
async def hent_resultat(job_id: str):
    job_id = _valider_job_id(job_id)
    pg = _pg()
    try:
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM results WHERE job_id = %s", (job_id,))
            rad = cur.fetchone()
        if rad is None:
            raise HTTPException(status_code=404, detail="Resultat ikke funnet")
        return dict(rad)
    except HTTPException:
        raise
    except Exception as feil:
        raise HTTPException(status_code=500, detail=str(feil))
    finally:
        pg.close()


# ------------------------------------------------------------------ #
#  GET /dokument/{dokument_id}/status — samlet status for alle sider   #
# ------------------------------------------------------------------ #

@ruter.get("/dokument/{dokument_id}/status")
async def dokument_status(dokument_id: str):
    """
    Samlet tilstand for et flersidig dokument:
      FAILED      — minst én side feilet
      DONE        — alle sider ferdige
      IN_PROGRESS — ellers
    """
    dokument_id = _valider_job_id(dokument_id)
    pg = _pg()
    try:
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT job_id, side_nummer, state FROM jobs "
                "WHERE dokument_id = %s ORDER BY side_nummer",
                (dokument_id,),
            )
            sider = cur.fetchall()
        if not sider:
            raise HTTPException(status_code=404, detail="Dokument ikke funnet")

        tilstander = [r["state"] for r in sider]
        if "FAILED" in tilstander:
            samlet = "FAILED"
        elif all(t == "DONE" for t in tilstander):
            samlet = "DONE"
        else:
            samlet = "IN_PROGRESS"
        return {
            "dokument_id": dokument_id,
            "state": samlet,
            "antall_sider": len(sider),
            "ferdige_sider": sum(1 for t in tilstander if t == "DONE"),
            "sider": [{"job_id": str(r["job_id"]),
                       "side_nummer": r["side_nummer"],
                       "state": r["state"]} for r in sider],
        }
    except HTTPException:
        raise
    except Exception as feil:
        raise HTTPException(status_code=500, detail=str(feil))
    finally:
        pg.close()


# ------------------------------------------------------------------ #
#  GET /dokument/{dokument_id}/felter — aggregerte felter (klienter)   #
# ------------------------------------------------------------------ #

@ruter.get("/dokument/{dokument_id}/felter")
async def dokument_felter(dokument_id: str):
    """
    Aggregert forretningskontrakt for hele dokumentet:
    felter = første ikke-tomme verdi per felt på tvers av sidene,
    beslutning = strengeste av sidenes beslutninger
    (REJECTED > REVIEW > APPROVED). 409 til alle sider er DONE.
    """
    dokument_id = _valider_job_id(dokument_id)
    pg = _pg()
    try:
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT j.job_id, j.side_nummer, j.state, j.file_name,
                       r.nlp_result, r.routing_decision, r.label_studio_project
                FROM jobs j
                LEFT JOIN results r ON r.job_id = j.job_id
                WHERE j.dokument_id = %s
                ORDER BY j.side_nummer
                """,
                (dokument_id,),
            )
            sider = cur.fetchall()
        if not sider:
            raise HTTPException(status_code=404, detail="Dokument ikke funnet")

        tilstander = [r["state"] for r in sider]
        if not all(t == "DONE" for t in tilstander):
            return JSONResponse(status_code=409, content={
                "dokument_id": dokument_id, "ferdig": False,
                "ferdige_sider": sum(1 for t in tilstander if t == "DONE"),
                "antall_sider": len(sider),
                "state": "FAILED" if "FAILED" in tilstander else "IN_PROGRESS",
            })

        feltnavn = ["navn", "fodselsnummer", "dato", "adresse",
                    "ytelse", "fylke", "telefon", "epost", "kontonummer",
                    "belop", "saksnummer", "kontornavn", "postnummer",
                    "poststed", "dokumenttype", "utfall", "oppsummering"]
        felter = {navn: None for navn in feltnavn}
        beslutninger, per_side = [], []
        for rad in sider:
            nlp = rad["nlp_result"] or {}
            entiteter = nlp.get("entities", {})
            side_felter = {
                "navn": entiteter.get("navn"),
                "fodselsnummer": entiteter.get("fodselsnummer"),
                "dato": entiteter.get("dato"),
                "adresse": entiteter.get("adresse"),
                "ytelse": entiteter.get("ytelse") or nlp.get("ytelse"),
                "fylke": entiteter.get("fylke"),
                "telefon": entiteter.get("telefon"),
                "epost": entiteter.get("epost"),
                "kontonummer": entiteter.get("kontonummer"),
                "belop": entiteter.get("belop"),
                "saksnummer": entiteter.get("saksnummer"),
                "kontornavn": entiteter.get("kontornavn"),
                "postnummer": entiteter.get("postnummer"),
                "poststed": entiteter.get("poststed"),
                "dokumenttype": nlp.get("document_class"),
                "utfall": nlp.get("utfall"),
                "oppsummering": nlp.get("summary"),
            }
            for navn in feltnavn:
                if felter[navn] is None and side_felter[navn]:
                    felter[navn] = side_felter[navn]
            beslutninger.append(rad["routing_decision"])
            per_side.append({
                "side_nummer": rad["side_nummer"],
                "job_id": str(rad["job_id"]),
                "beslutning": rad["routing_decision"],
                "felter": side_felter,
            })

        if "REJECTED" in beslutninger:
            samlet_beslutning = "REJECTED"
        elif "REVIEW" in beslutninger:
            samlet_beslutning = "REVIEW"
        else:
            samlet_beslutning = "APPROVED"

        return {
            "dokument_id": dokument_id,
            "ferdig": True,
            "state": "DONE",
            "filnavn": sider[0]["file_name"],
            "antall_sider": len(sider),
            "beslutning": samlet_beslutning,
            "felter": felter,
            "gjennomgang": {
                "kreves": samlet_beslutning in ("REVIEW", "REJECTED"),
                "sider_til_gjennomgang": [
                    s["side_nummer"] for s, b in zip(per_side, beslutninger)
                    if b in ("REVIEW", "REJECTED")
                ],
            },
            "per_side": per_side,
        }
    except HTTPException:
        raise
    except Exception as feil:
        raise HTTPException(status_code=500, detail=str(feil))
    finally:
        pg.close()


# ------------------------------------------------------------------ #
#  GET /dokument/{dokument_id}/tekst — hele dokumentet i sideorden     #
# ------------------------------------------------------------------ #

@ruter.get("/dokument/{dokument_id}/tekst")
async def dokument_tekst(
    dokument_id: str,
    fra_side: int = 0,
    til_side: int = None,
    tillat_delvis: bool = False,
):
    """
    Dokumentets OCR-tekst i ORIGINAL siderekkefølge — garantert sortert
    og nummerert som i PDF-en (ORDER BY side_nummer, INT). Sider
    prosesseres parallelt og kan bli ferdige i vilkårlig rekkefølge;
    dette endepunktet er stedet rekkefølgen gjenopprettes.

    Store dokumenter (1000+ sider): hent i sideintervaller med
    ?fra_side=0&til_side=49 (0-basert, til_side inklusiv) i stedet for
    å tvinge hele dokumentet inn i én respons.

    Standard: 409 til ALLE sider i intervallet er DONE (delvis tekst
    serveres aldri stille). Med ?tillat_delvis=true serveres ferdige
    sider med ferdig=false og manglende_sider — eksplisitt, aldri
    implisitt.

    MERK: Dette er et VISNINGS-/REVISJONSENDEPUNKT — rå OCR-tekst uten
    validering. Til forretningsuttrekk: bruk /dokument/{id}/felter
    (deterministisk validert kontrakt) eller /dokument/{id}/sporsmal
    (forankret LLM-svar). Å parse rå tekst selv omgår mod11-sjekkene,
    de kanoniske listene og anti-hallusinasjonslaget.
    """
    dokument_id = _valider_job_id(dokument_id)
    if fra_side < 0 or (til_side is not None and til_side < fra_side):
        raise HTTPException(status_code=400, detail="Ugyldig sideintervall")
    pg = _pg()
    try:
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT j.side_nummer, j.state, j.file_name, j.antall_sider,
                       r.ocr_result->>'text'        AS tekst,
                       r.ocr_result->>'confidence'  AS konfidens
                FROM jobs j
                LEFT JOIN results r ON r.job_id = j.job_id
                WHERE j.dokument_id = %s
                  AND j.side_nummer >= %s
                  AND (%s::int IS NULL OR j.side_nummer <= %s)
                ORDER BY j.side_nummer
                """,
                (dokument_id, fra_side, til_side, til_side),
            )
            sider = cur.fetchall()
        if not sider:
            raise HTTPException(
                status_code=404,
                detail="Dokument ikke funnet (eller tomt sideintervall)")

        antall_totalt = sider[0]["antall_sider"] or len(sider)
        manglende = [r["side_nummer"] for r in sider if r["state"] != "DONE"]
        if manglende and not tillat_delvis:
            return JSONResponse(status_code=409, content={
                "dokument_id": dokument_id, "ferdig": False,
                "ferdige_sider": len(sider) - len(manglende),
                "antall_sider": len(sider),
                "manglende_sider": manglende[:50],
                "hjelp": "Bruk ?tillat_delvis=true for de ferdige sidene",
            })

        sidetekster = [{
            "side_nummer": r["side_nummer"],
            "tekst": r["tekst"] or "",
            "ocr_konfidens": float(r["konfidens"]) if r["konfidens"] else 0.0,
        } for r in sider if r["state"] == "DONE"]

        return {
            "dokument_id": dokument_id,
            "filnavn": sider[0]["file_name"],
            "antall_sider": antall_totalt,
            "fra_side": fra_side,
            "til_side": til_side,
            "ferdig": not manglende,
            "manglende_sider": manglende,
            "sider": sidetekster,
            # Intervallet som én streng, med sidemarkører, i original orden
            "samlet_tekst": "\n\n".join(
                f"--- Side {s['side_nummer'] + 1} av {antall_totalt} ---\n{s['tekst']}"
                for s in sidetekster
            ),
        }
    except HTTPException:
        raise
    except Exception as feil:
        raise HTTPException(status_code=500, detail=str(feil))
    finally:
        pg.close()


# ------------------------------------------------------------------ #
#  GET /resultat/{job_id}/felter — flat kontrakt per side (klienter)   #
# ------------------------------------------------------------------ #

@ruter.get("/resultat/{job_id}/felter")
async def hent_felter(job_id: str):
    job_id = _valider_job_id(job_id)
    """
    Flat, stabil forretningskontrakt for eksterne klienter (RPA o.l.).
    409 til jobben er DONE — roboten poller /jobb/{id} først.
    Fødselsnummer serveres kun her (autentisert), aldri i søkeindeksen.
    """
    pg = _pg()
    try:
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT j.state, j.file_name,
                       r.nlp_result, r.routing_decision, r.label_studio_project
                FROM jobs j
                LEFT JOIN results r ON r.job_id = j.job_id
                WHERE j.job_id = %s
                """,
                (job_id,),
            )
            rad = cur.fetchone()
        if rad is None:
            raise HTTPException(status_code=404, detail="Jobb ikke funnet")
        if rad["state"] != "DONE":
            return JSONResponse(
                status_code=409,
                content={"job_id": job_id, "state": rad["state"], "ferdig": False},
            )

        nlp = rad["nlp_result"] or {}
        entiteter = nlp.get("entities", {})
        beslutning = rad["routing_decision"]
        return {
            "job_id": job_id,
            "state": rad["state"],
            "ferdig": True,
            "filnavn": rad["file_name"],
            "beslutning": beslutning,
            "felter": {
                "navn": entiteter.get("navn"),
                "fodselsnummer": entiteter.get("fodselsnummer"),
                "dato": entiteter.get("dato"),
                "adresse": entiteter.get("adresse"),
                "ytelse": entiteter.get("ytelse") or nlp.get("ytelse"),
                "fylke": entiteter.get("fylke"),
                "telefon": entiteter.get("telefon"),
                "epost": entiteter.get("epost"),
                "kontonummer": entiteter.get("kontonummer"),
                "belop": entiteter.get("belop"),
                "saksnummer": entiteter.get("saksnummer"),
                "kontornavn": entiteter.get("kontornavn"),
                "postnummer": entiteter.get("postnummer"),
                "poststed": entiteter.get("poststed"),
                "dokumenttype": nlp.get("document_class"),
                "utfall": nlp.get("utfall"),
                "oppsummering": nlp.get("summary"),
            },
            "konfidens": {
                "ocr": nlp.get("ocr_confidence"),
                "nlp": nlp.get("nlp_confidence"),
            },
            "gjennomgang": {
                "kreves": beslutning in ("REVIEW", "REJECTED"),
                "label_studio_prosjekt": rad["label_studio_project"],
            },
        }
    except HTTPException:
        raise
    except Exception as feil:
        raise HTTPException(status_code=500, detail=str(feil))
    finally:
        pg.close()


# ------------------------------------------------------------------ #
#  GET /audit/{job_id}                                                #
# ------------------------------------------------------------------ #

@ruter.get("/audit/{job_id}")
async def hent_audit(job_id: str):
    job_id = _valider_job_id(job_id)
    pg = _pg()
    try:
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, event_type, from_state, to_state, worker_id, details, created_at
                FROM audit_log WHERE job_id = %s ORDER BY created_at
                """,
                (job_id,),
            )
            rader = cur.fetchall()
        return [dict(r) for r in rader]
    except Exception as feil:
        raise HTTPException(status_code=500, detail=str(feil))
    finally:
        pg.close()
