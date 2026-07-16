"""
Sikkerhetskopi av Postgres — eneste kilde til sannhet i V2.1.

Strategi (dokumentert i docs/SIKKERHETSKOPI.md):
  - pg_dump i custom-format (-Fc): komprimert, kan gjenopprettes selektivt
  - sha256-sjekksum lagres ved siden av dumpen
  - Hver dump verifiseres med `pg_restore --list` før den regnes som gyldig
  - GFS-retention: N daglige, M ukentlige, K månedlige kopier beholdes
  - Valgfritt: inkrementell kopi av originaldokumenter (append-only —
    en fil i inntak/behandlet endres aldri etter skriving)
  - Hver kjøring logges i audit_log (event_type=SIKKERHETSKOPI)

Redis sikkerhetskopieres IKKE (ren transport — gjenoppbygges med
`make rebuild-redis`). Milvus sikkerhetskopieres IKKE (avledet data —
reindekseres fra Postgres + originalfiler).

Kun standardbibliotek + pg_dump/pg_restore/psql-binærer — ingen pip-krav.
Tilkobling via standard PG*-miljøvariabler (PGHOST, PGUSER, PGPASSWORD,
PGDATABASE) eller POSTGRES_URL.
"""
import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

logger = logging.getLogger("sikkerhetskopi")

BACKUP_STI = os.environ.get("BACKUP_STI", "/backup")
DATA_STI = os.environ.get("DATA_STI", "/data")
POSTGRES_URL = os.environ.get("POSTGRES_URL", "")

# GFS-retention (kan overstyres via miljø)
DAGLIGE = int(os.environ.get("BACKUP_DAGLIGE", "7"))
UKENTLIGE = int(os.environ.get("BACKUP_UKENTLIGE", "4"))
MAANEDLIGE = int(os.environ.get("BACKUP_MAANEDLIGE", "6"))

DUMP_PREFIKS = "nav_archive_"
DUMP_SUFFIKS = ".dump"
TIDSFORMAT = "%Y%m%d_%H%M%S"


# ------------------------------------------------------------------ #
#  Rene funksjoner (enhetstestet i tester/test_sikkerhetskopi.py)      #
# ------------------------------------------------------------------ #

def dump_navn(tidspunkt: datetime) -> str:
    return f"{DUMP_PREFIKS}{tidspunkt.strftime(TIDSFORMAT)}{DUMP_SUFFIKS}"


def parse_dump_tidspunkt(filnavn: str):
    """Trekker tidspunktet ut av et dump-filnavn. None hvis ukjent format."""
    if not (filnavn.startswith(DUMP_PREFIKS) and filnavn.endswith(DUMP_SUFFIKS)):
        return None
    raa = filnavn[len(DUMP_PREFIKS):-len(DUMP_SUFFIKS)]
    try:
        return datetime.strptime(raa, TIDSFORMAT)
    except ValueError:
        return None


def velg_filer_til_sletting(
    filnavn: list,
    naa: datetime,
    daglige: int = DAGLIGE,
    ukentlige: int = UKENTLIGE,
    maanedlige: int = MAANEDLIGE,
) -> list:
    """
    GFS-retention over dump-filnavn. Beholder:
      - ALLE kopier fra inneværende dag (manuelle kopier ryddes aldri
        samme dag de ble tatt)
      - nyeste kopi per dag for de `daglige` siste dagene
      - nyeste kopi per ISO-uke for de `ukentlige` siste ukene
      - nyeste kopi per måned for de `maanedlige` siste månedene
    Returnerer filnavnene som skal slettes. Filer med ukjent format
    røres aldri.
    """
    daterte = [(f, t) for f in filnavn if (t := parse_dump_tidspunkt(f))]
    daterte.sort(key=lambda ft: ft[1], reverse=True)  # nyest først

    behold = set()

    # Alt fra i dag beholdes
    for f, t in daterte:
        if t.date() == naa.date():
            behold.add(f)

    def _behold_nyeste_per(nokkel_fn, antall):
        sett = []
        for f, t in daterte:  # nyest først → første treff per nøkkel er nyest
            nokkel = nokkel_fn(t)
            if nokkel not in [n for n, _ in sett]:
                sett.append((nokkel, f))
            if len(sett) >= antall:
                break
        behold.update(f for _, f in sett)

    _behold_nyeste_per(lambda t: t.date(), daglige)
    _behold_nyeste_per(lambda t: t.isocalendar()[:2], ukentlige)   # (år, uke)
    _behold_nyeste_per(lambda t: (t.year, t.month), maanedlige)

    return [f for f, _ in daterte if f not in behold]


def sha256_fil(sti: str) -> str:
    h = hashlib.sha256()
    with open(sti, "rb") as f:
        for blokk in iter(lambda: f.read(1 << 20), b""):
            h.update(blokk)
    return h.hexdigest()


# ------------------------------------------------------------------ #
#  Postgres-operasjoner                                                #
# ------------------------------------------------------------------ #

def _pg_kommando(binær: str, *argumenter) -> list:
    """Bygger kommandolinje; POSTGRES_URL vinner over PG*-variabler."""
    cmd = [binær]
    if POSTGRES_URL:
        cmd += ["--dbname", POSTGRES_URL]
    return cmd + list(argumenter)


def ta_backup(maal_mappe: str = BACKUP_STI) -> dict:
    """Tar én full pg_dump, verifiserer og skriver sjekksum + status."""
    os.makedirs(maal_mappe, exist_ok=True)
    start = time.monotonic()
    naa = datetime.now()
    fil = os.path.join(maal_mappe, dump_navn(naa))
    midlertidig = fil + ".ufullstendig"

    logger.info("Starter pg_dump → %s", fil)
    subprocess.run(
        _pg_kommando("pg_dump", "--format=custom", "--file", midlertidig),
        check=True, capture_output=True,
    )

    # Verifiser FØR dumpen får sitt endelige navn — en kopi som ikke
    # kan leses av pg_restore er verdiløs og skal aldri se gyldig ut.
    verifiser_dump(midlertidig)
    os.replace(midlertidig, fil)

    sjekksum = sha256_fil(fil)
    with open(fil + ".sha256", "w", encoding="utf-8") as f:
        f.write(f"{sjekksum}  {os.path.basename(fil)}\n")

    resultat = {
        "fil": os.path.basename(fil),
        "bytes": os.path.getsize(fil),
        "sha256": sjekksum,
        "varighet_sekunder": round(time.monotonic() - start, 2),
        "tidspunkt": naa.isoformat(timespec="seconds"),
        "verifisert": True,
    }
    logger.info("Backup fullført: %s (%.1f MB på %.1fs)",
                resultat["fil"], resultat["bytes"] / 1e6,
                resultat["varighet_sekunder"])
    return resultat


def verifiser_dump(sti: str):
    """`pg_restore --list` leser hele TOC-en — feiler på korrupt dump."""
    subprocess.run(
        ["pg_restore", "--list", sti],
        check=True, capture_output=True,
    )


def verifiser_sjekksum(sti: str) -> bool:
    """Sammenligner dumpen mot lagret .sha256-fil."""
    sjekksum_fil = sti + ".sha256"
    if not os.path.exists(sjekksum_fil):
        logger.warning("Ingen sjekksumfil for %s", sti)
        return False
    with open(sjekksum_fil, encoding="utf-8") as f:
        forventet = f.read().split()[0]
    return sha256_fil(sti) == forventet


def rydd_gamle(maal_mappe: str = BACKUP_STI, naa: datetime = None) -> list:
    """Kjører GFS-retention; sletter dump + tilhørende sjekksumfil."""
    naa = naa or datetime.now()
    try:
        filer = sorted(os.listdir(maal_mappe))
    except FileNotFoundError:
        return []
    slettes = velg_filer_til_sletting(filer, naa)
    for f in slettes:
        for sti in (os.path.join(maal_mappe, f),
                    os.path.join(maal_mappe, f) + ".sha256"):
            if os.path.exists(sti):
                os.remove(sti)
        logger.info("Retention: slettet %s", f)
    return slettes


def gjenopprett(dump_fil: str, maal_database: str = None):
    """
    Gjenoppretter en dump. Uten --maal-database gjenopprettes rett inn i
    kildedatabasen (--clean --if-exists). Med --maal-database opprettes
    databasen først (idempotent) — brukt til restore-øvelser.
    Husk `make rebuild-redis` etterpå — Redis-køene skal alltid
    gjenoppbygges fra Postgres etter en gjenoppretting.
    """
    if not verifiser_sjekksum(dump_fil):
        raise SystemExit(f"Sjekksum stemmer ikke for {dump_fil} — avbryter.")
    verifiser_dump(dump_fil)

    if maal_database:
        subprocess.run(
            _pg_kommando("psql", "--command",
                         f'CREATE DATABASE "{maal_database}"'),
            check=False, capture_output=True,  # finnes fra før = OK
        )
        cmd = ["pg_restore", "--clean", "--if-exists", "--no-owner",
               "--dbname", _bytt_database(maal_database), dump_fil]
    else:
        cmd = _pg_kommando("pg_restore", "--clean", "--if-exists",
                           "--no-owner", dump_fil)
    logger.info("Gjenoppretter %s%s", dump_fil,
                f" → {maal_database}" if maal_database else "")
    subprocess.run(cmd, check=True, capture_output=True)
    logger.info("Gjenoppretting fullført. Kjør 'make rebuild-redis'.")


def _bytt_database(navn: str) -> str:
    """Bytter databasenavnet i POSTGRES_URL (eller bruker PG*-miljø)."""
    if POSTGRES_URL:
        base, _, _ = POSTGRES_URL.rpartition("/")
        return f"{base}/{navn}"
    return navn


def logg_til_audit(resultat: dict):
    """Skriver backup-hendelsen til audit_log — sporbarhet er NAV-krav."""
    detaljer = json.dumps(resultat).replace("'", "''")
    sql = (
        "INSERT INTO audit_log (event_type, worker_id, details) "
        f"VALUES ('SIKKERHETSKOPI', 'backup', '{detaljer}'::jsonb)"
    )
    try:
        subprocess.run(_pg_kommando("psql", "--command", sql),
                       check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        logger.warning("Klarte ikke logge til audit_log: %s", exc)


# ------------------------------------------------------------------ #
#  Originaldokumenter (append-only → inkrementell kopi er korrekt)     #
# ------------------------------------------------------------------ #

def kopier_nye_filer(kilde_rot: str = DATA_STI,
                     maal_mappe: str = BACKUP_STI) -> int:
    """Kopierer filer fra inntak/ og behandlet/ som ikke alt er kopiert.
    Filene er immutable etter skriving, så «finnes = ferdig» holder."""
    antall = 0
    for undermappe in ("inntak", "behandlet"):
        kilde = os.path.join(kilde_rot, undermappe)
        if not os.path.isdir(kilde):
            continue
        for rot, _, filer in os.walk(kilde):
            for fil in filer:
                kilde_fil = os.path.join(rot, fil)
                relativ = os.path.relpath(kilde_fil, kilde_rot)
                maal_fil = os.path.join(maal_mappe, "filer", relativ)
                if os.path.exists(maal_fil):
                    continue
                os.makedirs(os.path.dirname(maal_fil), exist_ok=True)
                shutil.copy2(kilde_fil, maal_fil)
                antall += 1
    if antall:
        logger.info("Kopierte %d nye originalfiler", antall)
    return antall


# ------------------------------------------------------------------ #
#  Kjøring                                                             #
# ------------------------------------------------------------------ #

def kjor_en_runde(inkluder_filer: bool) -> dict:
    resultat = ta_backup()
    resultat["slettet_av_retention"] = rydd_gamle()
    if inkluder_filer:
        resultat["nye_filer_kopiert"] = kopier_nye_filer()
    logg_til_audit(resultat)
    with open(os.path.join(BACKUP_STI, "status.json"), "w",
              encoding="utf-8") as f:
        json.dump(resultat, f, indent=2)
    return resultat


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--daemon", action="store_true",
                   help="Kjør kontinuerlig med fast intervall")
    p.add_argument("--intervall-timer", type=float,
                   default=float(os.environ.get("BACKUP_INTERVALL_TIMER", "24")))
    p.add_argument("--inkluder-filer", action="store_true",
                   default=os.environ.get("BACKUP_INKLUDER_FILER", "1") == "1")
    p.add_argument("--gjenopprett", metavar="DUMP_FIL",
                   help="Gjenopprett angitt dump i stedet for å ta backup")
    p.add_argument("--maal-database", metavar="NAVN",
                   help="Gjenopprett til denne databasen (restore-øvelse)")
    p.add_argument("--verifiser", metavar="DUMP_FIL",
                   help="Verifiser sjekksum + lesbarhet for en dump")
    args = p.parse_args()

    if args.verifiser:
        ok = verifiser_sjekksum(args.verifiser)
        verifiser_dump(args.verifiser)
        print(f"sjekksum={'OK' if ok else 'FEIL'} pg_restore --list=OK")
        sys.exit(0 if ok else 1)

    if args.gjenopprett:
        gjenopprett(args.gjenopprett, args.maal_database)
        return

    if args.daemon:
        logger.info("Backup-daemon: hver %.0f. time (GFS %d/%d/%d)",
                    args.intervall_timer, DAGLIGE, UKENTLIGE, MAANEDLIGE)
        while True:
            try:
                kjor_en_runde(args.inkluder_filer)
            except Exception:
                logger.exception("Backup-runde feilet — prøver igjen "
                                 "ved neste intervall")
            time.sleep(args.intervall_timer * 3600)
    else:
        kjor_en_runde(args.inkluder_filer)


if __name__ == "__main__":
    main()
