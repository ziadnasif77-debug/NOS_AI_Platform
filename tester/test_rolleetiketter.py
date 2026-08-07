"""«Legens navn» gjør ikke legen til dokumentets part (R155).

Dette er det farligste enkeltfeltet i hele API-et: `part.fnr` er svaret
på «hvem gjelder dette». Var det feil, ble et vedtak knyttet til feil
menneske — og hens fødselsnummer og fødselsdato levert som dokumentets
egne.

TO FEIL SOM FORSTERKET HVERANDRE
1. `\\blege\\b` traff ikke «legens». Genitivsformen er den vanligste
   måten et norsk skjema spør på, og den falt utenfor lista over ANDRE
   roller.
2. «Sist vinner»-regelen gjelder MELLOM linjer — et dokument leses
   ovenfra og ned. Inne i ÉN linje er «Legens navn» en eieform:
   rolleordet står først og styrer substantivet etter. Med sist-vinner
   slo `navn` derfor `lege` hver eneste gang, fordi eieformen setter
   dem i akkurat den rekkefølgen.

Målt før rettingen: 15 av 15 rolleetiketter gjorde rolleinnehaveren til
dokumentets part — med `fastslatt: true`, `grunnlag: "etikett"`,
`sammendrag.konfidens: "hoy"` og `varsler: []`. Hver eneste uavhengige
indikator i svaret sa «vi er sikre», og personen var feil.
"""
import os
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from delt import dokumentprofil as dp
from syntetiske_nummer import lag_fnr

FNR = lag_fnr(0)
FNR2 = lag_fnr(1)

ANDRE_ROLLER = [
    "Legens", "Fastlegens", "Tannlegens", "Psykologens",
    "Fysioterapeutens", "Behandlers", "Saksbehandlers", "Arbeidsgivers",
    "Kontaktpersonens", "Vergens", "Fullmektiges", "Avsenders",
    "Mottakers", "Veileders", "Konsulentens",
]

EIERROLLER = ["Sokers", "Brukers", "Den sykmeldtes", "Pasientens"]


@pytest.mark.parametrize("rolle", ANDRE_ROLLER)
def test_rolleinnehaveren_blir_ikke_dokumentets_part(rolle):
    """Navngitt per rolle, så en rød test sier HVILKEN etikett som
    snudde."""
    tekst = (f"NAV Legeerklaering\n{rolle} navn: Per Hansen\n"
             f"Fodselsnummer: {FNR}\n")
    eier = dp.finn_dokument_eier(tekst)
    assert not (eier and eier.get("fnr") == FNR), (
        f"«{rolle} navn» gjorde rolleinnehaveren til dokumentets part")


@pytest.mark.parametrize("rolle", EIERROLLER)
def test_ekte_eieretiketter_virker_fortsatt(rolle):
    """Speilet. Uten dette kunne rettingen «løses» ved å slutte å finne
    en part i det hele tatt — og testen over ville vært grønn."""
    tekst = f"NAV Vedtak\n{rolle} navn: Ola Nordmann\nFodselsnummer: {FNR}\n"
    eier = dp.finn_dokument_eier(tekst)
    assert eier and eier.get("fnr") == FNR, (
        f"«{rolle} navn» fant ikke lenger dokumentets part")


def test_den_bare_navn_formen_virker_fortsatt():
    """Et dokument som bare skriver «Navn:» har ingen konkurrerende
    rolle, og da er det dokumentets egen person."""
    eier = dp.finn_dokument_eier(
        f"NAV Vedtak\nNavn: Ola Nordmann\nFodselsnummer: {FNR}\n")
    assert eier and eier.get("fnr") == FNR


def test_sist_vinner_gjelder_fortsatt_mellom_linjer():
    """Regelen er riktig MELLOM linjer: står «Saksbehandler:» rett over
    nummeret, er det saksbehandlerens — selv om «Dokumentet gjelder»
    sto lenger opp. Rettingen skal bare gjelde inne i én linje."""
    tekst = (f"Dokumentet gjelder: Ola Nordmann\n"
             f"Saksbehandler: Kari Hansen\nFodselsnummer: {FNR}\n")
    eier = dp.finn_dokument_eier(tekst)
    assert not (eier and eier.get("fnr") == FNR), (
        "saksbehandlerens nummer ble dokumentets")


def test_begge_personene_i_et_ekte_dokument():
    """Hele saken: en legeerklæring med BÅDE pasienten og legen.
    Pasienten skal bli part, legen skal havne i «andre»."""
    tekst = (f"NAV Legeerklaering\n"
             f"Pasientens navn: Ola Nordmann\n"
             f"Fodselsnummer: {FNR}\n"
             f"Legens navn: Per Hansen\n"
             f"Fodselsnummer: {FNR2}\n")
    eier = dp.finn_dokument_eier(tekst)
    assert eier and eier.get("fnr") == FNR, "pasienten ble ikke part"
    andre = [a.get("fnr") for a in (eier.get("andre_fodselsnummer") or [])]
    assert FNR2 in andre, "legens nummer forsvant helt"


def test_bare_legens_nummer_gir_ingen_part():
    """Står det bare ett nummer, og etiketten sier at det tilhører en
    annen rolle, er svaret `null` — ikke nummeret. «Det står bare ett
    her» er en gjetning om hvem et vedtak gjelder."""
    eier = dp.finn_dokument_eier(
        f"NAV Legeerklaering\nLegens navn: Per Hansen\n"
        f"Fodselsnummer: {FNR}\n")
    assert eier.get("fnr") is None
    andre = [a.get("fnr") for a in (eier.get("andre_fodselsnummer") or [])]
    assert FNR in andre, "nummeret skal fortsatt være med, bare atskilt"
