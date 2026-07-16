"""
Oppbevaringsbegrensning (GDPR / NAV-krav: dokumenter maks 6 måneder).

Sletter ALT dokumentinnhold for jobber eldre enn `maks_dager`:
  1. Originalfiler + siderendrede PNG/PDF-er på disk
  2. `results`-raden (OCR-tekst, entiteter — persondata)
  3. `payload_snapshot` i dead_letter_queue
  4. Milvus-søkeindeksen (DELETE /dokument/{fil_id} på søketjenesten)
  5. jobs-raden anonymiseres (filnavn/sti/feiltekst fjernes) men
     BEHOLDES — prosesstatistikk uten innhold
`audit_log` beholdes for alltid (NAV-krav) — den inneholder kun
tekniske hendelser, aldri dokumentinnhold. Hver sletting logges dit
(event_type=SLETTET_OPPBEVARING) som BEVIS på at kravet etterleves.

Totalbudsjett: maks_dager + eldste sikkerhetskopi ≤ 180 dager.
Standard: 150 dagers oppbevaring + ≤ 28 dagers backup-retention
(BACKUP_MAANEDLIGE=0). Se docs/OPPBEVARING.md.

Kjøres som daemon (compose) eller CronJob (K8s). --torrkjoring viser
hva som VILLE blitt slettet uten å røre noe.
"""
import argparse
import json
import logging
import os
import time
from datetime import datetime, timedelta

logger = logging.getLogger("oppbevaring")

POSTGRES_URL = os.environ.get(
    "POSTGRES_URL", "postgresql://nav:nav@localhost:5432/nav_archive"
)
SOK_URL = os.environ.get("SOK_URL", "http://sok:8003")
API_NOKKEL = os.environ.get("API_NOKKEL", "")
DATA_STI = os.environ.get("DATA_STI", "/data")
MAKS_DAGER = int(os.environ.get("OPPBEVARING_MAKS_DAGER", "150"))
LABEL_STUDIO_URL = os.environ.get("LABEL_STUDIO_URL", "")
LABEL_STUDIO_API_KEY = os.environ.get("LABEL_STUDIO_API_KEY", "")


# ------------------------------------------------------------------ #
#  Rene hjelpefunksjoner (enhetstestet)                                #
# ------------------------------------------------------------------ #

def beregn_frist(naa: datetime, maks_dager: int) -> datetime:
    return naa - timedelta(days=maks_dager)


def samle_filstier(file_path, preprocess_result, ocr_result) -> list:
    """Alle disk-stier knyttet til en jobb — original + avledede filer.
    Duplikater fjernes, tomme ignoreres."""
    stier = [file_path]
    for res, nokler in (
        (preprocess_result, ("preprocessed_path", "side_pdf_sti")),
        (ocr_result, ("raw_path", "clean_path")),
    ):
        if isinstance(res, dict):
            stier.extend(res.get(n) for n in nokler)
    sett, resultat = set(), []
    for s in stier:
        if s and s not in sett:
            sett.add(s)
            resultat.append(s)
    return resultat


def gyldig_fil_id(fil_id: str) -> bool:
    """Samme regel som søketjenesten — hindrer uttrykks-injeksjon."""
    return bool(fil_id) and fil_id.replace("-", "").isalnum() and len(fil_id) <= 200


# ------------------------------------------------------------------ #
#  Sletting                                                            #
# ------------------------------------------------------------------ #

def finn_utlopte(pg, frist: datetime) -> list:
    """Jobber i terminal tilstand, eldre enn fristen, ikke alt ryddet
    (tom file_path er ferdig-markør — kolonnen er NOT NULL)."""
    with pg.cursor() as cur:
        cur.execute(
            """
            SELECT j.job_id, j.dokument_id, j.file_path,
                   r.preprocess_result, r.ocr_result,
                   COALESCE(j.completed_at, j.updated_at) AS ferdig
            FROM jobs j
            LEFT JOIN results r ON r.job_id = j.job_id
            WHERE j.state IN ('DONE', 'FAILED')
              AND COALESCE(j.completed_at, j.updated_at) < %s
              AND (j.file_path <> '' OR r.job_id IS NOT NULL)
            ORDER BY ferdig
            """,
            (frist,),
        )
        kolonner = [k.name for k in cur.description]
        return [dict(zip(kolonner, rad)) for rad in cur.fetchall()]


def slett_filer(stier: list, torrkjoring: bool) -> int:
    antall = 0
    for sti in stier:
        if not os.path.isfile(sti):
            continue
        if not torrkjoring:
            os.remove(sti)
        antall += 1
    return antall


def slett_fra_sokeindeks(fil_id: str, torrkjoring: bool) -> bool:
    if not gyldig_fil_id(fil_id):
        return False
    if torrkjoring:
        return True
    import requests
    try:
        resp = requests.delete(
            f"{SOK_URL}/dokument/{fil_id}",
            headers={"X-API-Key": API_NOKKEL},
            timeout=30,
        )
        # 503 = Milvus nede: rapporter feil så jobben prøves igjen i
        # neste runde (file_path nulles ikke før alt er borte? — jo,
        # DB/filer er viktigst; indeksen logges og tas neste runde)
        return resp.status_code == 200
    except Exception as exc:
        logger.warning("Søkeindeks-sletting feilet for %s: %s", fil_id, exc)
        return False


def slett_jobb_innhold(pg, job_id: str, torrkjoring: bool):
    """Fjerner alt innhold i Postgres for én jobb; beholder metadata."""
    if torrkjoring:
        return
    with pg.cursor() as cur:
        cur.execute("DELETE FROM results WHERE job_id = %s", (job_id,))
        cur.execute(
            """
            UPDATE dead_letter_queue
            SET payload_snapshot = '{"slettet": "oppbevaring"}'::jsonb,
                error_message = '[slettet: oppbevaring]'
            WHERE job_id = %s
            """,
            (job_id,),
        )
        cur.execute(
            """
            UPDATE jobs
            SET file_name = '[slettet: oppbevaring]',
                file_path = '',              -- kolonnen er NOT NULL; tom = ryddet
                last_error = NULL
            WHERE job_id = %s
            """,
            (job_id,),
        )
    pg.commit()


def logg_sletting(pg, job_id: str, detaljer: dict):
    with pg.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_log (job_id, event_type, worker_id, details)
            VALUES (%s, 'SLETTET_OPPBEVARING', 'oppbevaring', %s)
            """,
            (job_id, json.dumps(detaljer)),
        )
    pg.commit()


def rydd_label_studio(frist: datetime, torrkjoring: bool) -> int:
    """Best effort: slett gjennomgangsoppgaver eldre enn fristen.
    Manglende Label Studio-oppsett er ikke en feil — bare hopp over."""
    if not (LABEL_STUDIO_URL and LABEL_STUDIO_API_KEY):
        return 0
    import requests
    slettet = 0
    try:
        hoder = {"Authorization": f"Token {LABEL_STUDIO_API_KEY}"}
        prosjekter = requests.get(
            f"{LABEL_STUDIO_URL}/api/projects", headers=hoder, timeout=30
        ).json()
        for p in prosjekter.get("results", prosjekter if isinstance(prosjekter, list) else []):
            oppgaver = requests.get(
                f"{LABEL_STUDIO_URL}/api/tasks",
                params={"project": p["id"], "page_size": 500},
                headers=hoder, timeout=60,
            ).json()
            for oppgave in oppgaver.get("tasks", []):
                opprettet = oppgave.get("created_at", "")[:19]
                try:
                    t = datetime.fromisoformat(opprettet)
                except ValueError:
                    continue
                if t < frist:
                    if not torrkjoring:
                        requests.delete(
                            f"{LABEL_STUDIO_URL}/api/tasks/{oppgave['id']}",
                            headers=hoder, timeout=30,
                        )
                    slettet += 1
    except Exception as exc:
        logger.warning("Label Studio-opprydding hoppet over: %s", exc)
    return slettet


RETRY_STI = os.path.join(DATA_STI, ".oppbevaring_indeks_retry.json")


def _last_retryliste() -> set:
    """Dokument-IDer der indeks-sletting feilet (Milvus nede) i en
    tidligere runde — DB/filer er alt slettet, kun indeksen gjenstår."""
    try:
        with open(RETRY_STI, encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _lagre_retryliste(fil_ider: set):
    if fil_ider:
        with open(RETRY_STI, "w", encoding="utf-8") as f:
            json.dump(sorted(fil_ider), f)
    elif os.path.exists(RETRY_STI):
        os.remove(RETRY_STI)


def kjor_en_runde(maks_dager: int, torrkjoring: bool) -> dict:
    import psycopg2
    naa = datetime.now()
    frist = beregn_frist(naa, maks_dager)
    prefiks = "[TØRRKJØRING] " if torrkjoring else ""
    logger.info("%sSletter dokumentinnhold eldre enn %s (%d dager)",
                prefiks, frist.date(), maks_dager)

    pg = psycopg2.connect(POSTGRES_URL)
    try:
        # Først: nye forsøk på indeks-slettinger som feilet tidligere
        indeks_venter = _last_retryliste()
        for fil_id in sorted(indeks_venter.copy()):
            if slett_fra_sokeindeks(fil_id, torrkjoring):
                indeks_venter.discard(fil_id)
                if not torrkjoring:
                    logg_sletting(pg, None, {
                        "fil_id": fil_id, "sokeindeks": True,
                        "retry": True, "maks_dager": maks_dager,
                    })

        utlopte = finn_utlopte(pg, frist)
        dokumenter_slettet = set()
        filer_slettet = 0

        for jobb in utlopte:
            stier = samle_filstier(
                jobb["file_path"], jobb["preprocess_result"], jobb["ocr_result"]
            )
            antall_filer = slett_filer(stier, torrkjoring)
            filer_slettet += antall_filer

            fil_id = str(jobb["dokument_id"] or jobb["job_id"])
            if fil_id not in dokumenter_slettet:
                if slett_fra_sokeindeks(fil_id, torrkjoring):
                    dokumenter_slettet.add(fil_id)
                elif not torrkjoring:
                    indeks_venter.add(fil_id)   # tas i neste runde

            slett_jobb_innhold(pg, jobb["job_id"], torrkjoring)
            if not torrkjoring:
                logg_sletting(pg, jobb["job_id"], {
                    "fil_id": fil_id,
                    "alder_dager": (naa - jobb["ferdig"]).days,
                    "filer_slettet": antall_filer,
                    "sokeindeks": fil_id in dokumenter_slettet,
                    "maks_dager": maks_dager,
                })

        if not torrkjoring:
            _lagre_retryliste(indeks_venter)

        ls_slettet = rydd_label_studio(frist, torrkjoring)

        resultat = {
            "jobber": len(utlopte),
            "filer": filer_slettet,
            "dokumenter_fra_indeks": len(dokumenter_slettet),
            "indeks_venter_retry": len(indeks_venter),
            "label_studio_oppgaver": ls_slettet,
            "torrkjoring": torrkjoring,
        }
        logger.info("%sFerdig: %s", prefiks, resultat)
        return resultat
    finally:
        pg.close()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--maks-dager", type=int, default=MAKS_DAGER)
    p.add_argument("--torrkjoring", action="store_true",
                   help="Vis hva som ville blitt slettet — rør ingenting")
    p.add_argument("--daemon", action="store_true")
    p.add_argument("--intervall-timer", type=float,
                   default=float(os.environ.get("OPPBEVARING_INTERVALL_TIMER", "24")))
    args = p.parse_args()

    if args.daemon:
        logger.info("Oppbevaring-daemon: hver %.0f. time, maks %d dager",
                    args.intervall_timer, args.maks_dager)
        while True:
            try:
                kjor_en_runde(args.maks_dager, args.torrkjoring)
            except Exception:
                logger.exception("Oppbevaringsrunde feilet — prøver igjen "
                                 "ved neste intervall")
            time.sleep(args.intervall_timer * 3600)
    else:
        kjor_en_runde(args.maks_dager, args.torrkjoring)


if __name__ == "__main__":
    main()
