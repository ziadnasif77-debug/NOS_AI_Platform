"""
Enhetstester for sikkerhetskopi-logikken (skript/sikkerhetskopi.py).
Kun rene funksjoner — pg_dump/pg_restore dekkes av live-prosedyren
i docs/SIKKERHETSKOPI.md.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skript.sikkerhetskopi import (
    dump_navn, parse_dump_tidspunkt, velg_filer_til_sletting, sha256_fil,
)

NAA = datetime(2026, 7, 16, 12, 0, 0)


def _navn(t: datetime) -> str:
    return dump_navn(t)


# ------------------------------------------------------------------ #
#  Filnavn                                                             #
# ------------------------------------------------------------------ #

def test_dump_navn_rundtur():
    t = datetime(2026, 7, 16, 2, 0, 5)
    assert parse_dump_tidspunkt(dump_navn(t)) == t


def test_parse_avviser_fremmede_filer():
    assert parse_dump_tidspunkt("status.json") is None
    assert parse_dump_tidspunkt("nav_archive_ugyldig.dump") is None
    assert parse_dump_tidspunkt("nav_archive_20260716_020005.dump.sha256") is None


# ------------------------------------------------------------------ #
#  GFS-retention                                                       #
# ------------------------------------------------------------------ #

def test_retention_beholder_alt_fra_i_dag():
    filer = [_navn(NAA - timedelta(hours=h)) for h in range(0, 10, 3)]
    slettes = velg_filer_til_sletting(filer, NAA)
    assert slettes == []


def test_retention_en_per_dag_utover_dagens():
    """To kopier samme gårsdag → kun nyeste beholdes."""
    tidlig = NAA - timedelta(days=1, hours=8)
    sent = NAA - timedelta(days=1, hours=1)
    slettes = velg_filer_til_sletting([_navn(tidlig), _navn(sent)], NAA)
    assert slettes == [_navn(tidlig)]


def test_retention_daglige_grense():
    """14 dager med daglige kopier, daglige=7 → dag 8–14 dekkes kun
    av uke-/månedsregelen."""
    filer = [_navn(NAA - timedelta(days=d)) for d in range(14)]
    slettes = velg_filer_til_sletting(filer, NAA, daglige=7,
                                      ukentlige=0, maanedlige=0)
    beholdt = set(filer) - set(slettes)
    assert len(beholdt) == 7
    # de 7 nyeste dagene er de som beholdes
    assert all(_navn(NAA - timedelta(days=d)) in beholdt for d in range(7))


def test_retention_ukentlige_beholder_nyeste_per_uke():
    filer = [_navn(NAA - timedelta(days=d)) for d in range(30)]
    slettes = velg_filer_til_sletting(filer, NAA, daglige=1,
                                      ukentlige=4, maanedlige=0)
    beholdt = set(filer) - set(slettes)
    uker = {parse_dump_tidspunkt(f).isocalendar()[:2] for f in beholdt}
    assert len(uker) >= 4  # minst 4 distinkte uker representert


def test_retention_maanedlige_over_lang_tid():
    filer = [_navn(NAA - timedelta(days=30 * m + 3)) for m in range(10)]
    slettes = velg_filer_til_sletting(filer, NAA, daglige=1,
                                      ukentlige=1, maanedlige=6)
    beholdt = set(filer) - set(slettes)
    maaneder = {(parse_dump_tidspunkt(f).year, parse_dump_tidspunkt(f).month)
                for f in beholdt}
    assert len(maaneder) >= 6


def test_retention_rorer_aldri_ukjente_filer():
    filer = ["status.json", "notat.txt",
             _navn(NAA - timedelta(days=400))]
    slettes = velg_filer_til_sletting(filer, NAA)
    assert "status.json" not in slettes
    assert "notat.txt" not in slettes


def test_retention_tom_liste():
    assert velg_filer_til_sletting([], NAA) == []


# ------------------------------------------------------------------ #
#  Sjekksum                                                            #
# ------------------------------------------------------------------ #

def test_sha256_fil(tmp_path):
    fil = tmp_path / "test.dump"
    fil.write_bytes(b"nav-arkiv")
    import hashlib
    assert sha256_fil(str(fil)) == hashlib.sha256(b"nav-arkiv").hexdigest()
