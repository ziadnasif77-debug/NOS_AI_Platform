"""
Gjenopptar jobber fra dead_letter_queue etter at rotårsaken er fikset.

Bruksområde: jobber som havnet i DLQ på grunn av en INFRASTRUKTURFEIL
(manglende bibliotek, nede tjeneste) — ikke fordi selve dokumentet var
umulig å behandle. Etter fiksen fortjener de en ny kjøring i stedet for
å stå som «endelig feilet» og forurense feilraten i historiske metrikker.

For hver treffende, uløst DLQ-rad:
  1. payload_snapshot (den eksakte meldingen workeren konsumerte)
     re-køes til stadiets Redis-kø, med retry_count nullstilt
  2. jobs-raden settes tilbake til stadiets FØR-tilstand og
     attempt_count nullstilles
  3. DLQ-raden markeres løst (resolved_at + resolved_by=merkelappen)
  4. audit_log får GJENOPPTATT_FRA_DLQ med merkelapp — historiske
     analyser kan dermed skille «ekte feil» fra «infrastruktur-bugg»

Eksempel (Label Studio-avhengighetsbuggen, juli 2026):
  python skript/dlq_gjenoppta.py \
      --monster "No module named 'requests'" \
      --merkelapp ls-avhengighet-bugg-2026
"""
import argparse
import json
import logging
import os
import sys

sys.path.insert(0, ".")
from config.config_loader import CONFIG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dlq_gjenoppta")

POSTGRES_URL = os.environ.get("POSTGRES_URL", CONFIG["postgres"]["url"])
REDIS_URL = os.environ.get("REDIS_URL", CONFIG["redis"]["url"])

# DLQ.stage er workerens running_state — jobben settes tilbake til
# FØR-tilstanden slik at workerens normale blpop-overgang gjelder.
STAGE_TIL_KO_OG_FORTILSTAND = {
    "PREPROCESSING":  (CONFIG["redis"]["kooer"]["preprocess"], "QUEUED"),
    "OCR_PROCESSING": (CONFIG["redis"]["kooer"]["ocr"],        "PREPROCESSING"),
    "NLP_PROCESSING": (CONFIG["redis"]["kooer"]["nlp"],        "OCR_PROCESSING"),
    "ROUTING":        (CONFIG["redis"]["kooer"]["routing"],    "NLP_PROCESSING"),
}


def gjenoppta(monster: str, merkelapp: str, torrkjoring: bool) -> int:
    import psycopg2, psycopg2.extras, redis as redis_lib
    pg = psycopg2.connect(POSTGRES_URL)
    r = redis_lib.from_url(REDIS_URL, decode_responses=True)

    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT d.id, d.job_id, d.stage, d.error_type, d.error_message,
                   d.payload_snapshot
            FROM dead_letter_queue d
            JOIN jobs j ON j.job_id = d.job_id
            WHERE d.resolved_at IS NULL
              AND j.state = 'FAILED'
              AND d.error_message ILIKE %s
            ORDER BY d.id
            """,
            (f"%{monster}%",),
        )
        rader = cur.fetchall()

    if not rader:
        logger.info("Ingen uløste DLQ-rader matcher «%s».", monster)
        return 0

    prefiks = "[TØRRKJØRING] " if torrkjoring else ""
    antall = 0
    for rad in rader:
        stage = rad["stage"]
        if stage not in STAGE_TIL_KO_OG_FORTILSTAND:
            logger.warning("Ukjent stage «%s» for %s — hopper over",
                           stage, rad["job_id"])
            continue
        ko, for_tilstand = STAGE_TIL_KO_OG_FORTILSTAND[stage]

        payload = dict(rad["payload_snapshot"] or {})
        if "job_id" not in payload:
            logger.warning("Tomt/ugyldig payload_snapshot for %s — hopper over",
                           rad["job_id"])
            continue
        payload["retry_count"] = 0   # frisk start etter fikset rotårsak

        logger.info("%s%s (%s: %s) → %s", prefiks, rad["job_id"],
                    rad["error_type"], (rad["error_message"] or "")[:60], ko)
        antall += 1
        if torrkjoring:
            continue

        with pg.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET state = %s, attempt_count = 0, last_error = NULL,
                    completed_at = NULL, locked_by = NULL, lock_expiry = NULL,
                    updated_at = NOW()
                WHERE job_id = %s
                """,
                (for_tilstand, str(rad["job_id"])),
            )
            cur.execute(
                """
                UPDATE dead_letter_queue
                SET resolved_at = NOW(), resolved_by = %s
                WHERE id = %s
                """,
                (f"gjenopptak:{merkelapp}", rad["id"]),
            )
            cur.execute(
                """
                INSERT INTO audit_log
                  (job_id, event_type, from_state, to_state, worker_id, details)
                VALUES (%s, 'GJENOPPTATT_FRA_DLQ', 'FAILED', %s, 'dlq_gjenoppta', %s)
                """,
                (str(rad["job_id"]), for_tilstand, psycopg2.extras.Json({
                    "merkelapp": merkelapp,
                    "stage": stage,
                    "opprinnelig_feil": (rad["error_message"] or "")[:200],
                })),
            )
        pg.commit()
        # Commit FØR rpush (samme mønster som API-et): krasjer vi her,
        # plukker ghost-detektoren opp jobben.
        r.rpush(ko, json.dumps(payload))

    logger.info("%s%d jobber gjenopptatt (merkelapp: %s)",
                prefiks, antall, merkelapp)
    pg.close()
    return antall


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--monster", required=True,
                   help="Delstreng som matches mot error_message (ILIKE)")
    p.add_argument("--merkelapp", default="manuelt-gjenopptak",
                   help="Skrives til resolved_by og audit — skiller "
                        "infrastruktur-bugger fra ekte feil i historikken")
    p.add_argument("--torrkjoring", action="store_true")
    args = p.parse_args()
    gjenoppta(args.monster, args.merkelapp, args.torrkjoring)


if __name__ == "__main__":
    main()
