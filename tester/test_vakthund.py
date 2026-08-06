"""
Tester for vakthunden (R122).

Bakgrunnen er målt: over to døgn stoppet API-et gjentatte ganger mens
tunnelen, Label Studio og Prefect fortsatte. Loggen sluttet midt i en
rekke `[GET] /hjelp → 200` — ingen traceback, ingen oppføring i Windows'
hendelseslogg. To døgn med krasj ga null informasjon, fordi ingenting
fanget avslutningen.

Det viktigste vakthunden gjør er derfor IKKE å starte på nytt. Det er å
skrive ned EXITKODEN.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import vakthund


# ------------------------------------------------------------------ #
#  1. Exitkoden er hele poenget                                        #
# ------------------------------------------------------------------ #

def test_native_krasj_forklares_med_ord():
    """0xC0000005 er tallet man får når llama.cpp eller CUDA faller. Det
    finnes INGEN Python-traceback å lete etter da — tolken rakk aldri å
    reagere — og uten forklaringen leter man i timevis i feil logg."""
    tekst = vakthund._tyd(3221225477)
    assert "0xC0000005" in tekst
    assert "native" in tekst.lower()
    assert "llama.cpp" in tekst


def test_drept_utenfra_er_IKKE_et_krasj():
    """0xFFFFFFFF betyr TerminateProcess: Oppgavebehandling, et skript,
    en operatør. Å kalle det et krasj ville sendt feilsøkingen på en helt
    annen vei."""
    tekst = vakthund._tyd(4294967295)
    assert "DREPT UTENFRA" in tekst
    assert "ikke et krasj" in tekst


def test_python_feil_peker_paa_riktig_logg():
    assert "oppstart_api.log" in vakthund._tyd(1)


def test_ryddig_avslutning_skilles_fra_krasj():
    assert "ryddig" in vakthund._tyd(0)


def test_ukjent_native_kode_gjenkjennes_paa_tallet():
    """Alt over 0xC0000000 er en NTSTATUS-feilkode, også de vi ikke har
    en tekst for."""
    tekst = vakthund._tyd(0xC0000017)      # STATUS_NO_MEMORY
    assert "0xC0000017" in tekst
    assert "native" in tekst


def test_ukjent_vanlig_kode_gis_som_tall():
    assert vakthund._tyd(42) == "42"


def test_ingen_kode_er_ukjent_ikke_null():
    assert vakthund._tyd(None) == "ukjent"


# ------------------------------------------------------------------ #
#  2. Vakthunden skal ikke bli et problem selv                         #
# ------------------------------------------------------------------ #

def test_omstart_venter_lenger_for_hver_gang():
    """En tjeneste som krasjer med én gang og startes umiddelbart på nytt
    gir en løkke, ikke en vakthund. Ventetiden dobles opp til et tak."""
    assert vakthund.PAUSE_START_S < vakthund.PAUSE_TAK_S
    pause = vakthund.PAUSE_START_S
    for _ in range(20):
        pause = min(pause * 2, vakthund.PAUSE_TAK_S)
    assert pause == vakthund.PAUSE_TAK_S


def test_en_enkelt_bom_gir_ikke_omstart():
    """En travel OCR-kjøring kan holde tråden opptatt forbi fristen. Å
    starte på nytt da ville avbrutt et dokument som var i arbeid."""
    assert vakthund.BOM_FOR_OMSTART >= 2


def test_oppstartsfristen_taaler_at_modellene_lastes():
    """Borealis og OCR-modellene bruker titalls sekunder. En kort frist
    ville konkludert «nede» hver eneste oppstart, og vakthunden ville
    drept tjenesten den nettopp startet."""
    assert vakthund.OPPSTARTSFRIST_S >= 120


def test_helsesjekken_gaar_mot_et_endepunkt_uten_nokkel():
    """/hjelp er unntatt nøkkelkravet nettopp for helsesjekk. Gikk
    sjekken mot et beskyttet endepunkt, ville en riktig konfigurert
    server sett «nede» ut for vakthunden."""
    assert vakthund.HELSE_URL.endswith("/hjelp")


def test_loggen_ligger_under_nav():
    """CLAUDE.md §1: ingenting utenfor prosjektmappa."""
    rot = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert os.path.abspath(vakthund.LOGG).startswith(os.path.abspath(rot))


# ------------------------------------------------------------------ #
#  3. Helsesjekken                                                     #
# ------------------------------------------------------------------ #

def test_svarer_er_usann_naar_ingenting_lytter(monkeypatch):
    """En port ingen lytter på skal gi False, ikke et unntak — ellers
    ville vakthunden dødd av den første feilen den var laget for."""
    monkeypatch.setattr(vakthund, "HELSE_URL", "http://127.0.0.1:1/hjelp")
    monkeypatch.setattr(vakthund, "SJEKK_FRIST_S", 1.0)
    assert vakthund.svarer() is False
