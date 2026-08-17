"""
ADR-malen er obligatorisk — og var uten vakt (§29.1).

Registeret har regelen skrevet ned selv: «Malen i MAL.md er obligatorisk.
Alle felter fylles ut. Står et felt tomt, er beslutningen ikke tatt
ennå.» Og: «En midlertidig løsning uten review trigger er ikke tillatt.»

Ingenting håndhevet det. Det er samme mønster som R212 fant i
sikkerhetskontrollene: en regel uten test er en vane, og vaner overlever
ikke en travel fredag. Verst blir det her, for en ADR skrives ofte når
noen har dårlig tid — det er nettopp da et felt blir stående tomt, og
nettopp da beslutningen trenger å være fullstendig.

DE TO FELTENE SOM BETYR MEST
`Owner` skal være et NAVN. En rolle kan ikke svare når triggeren slår
inn — «plattformteamet» leser ingen ADR.

`Review Trigger` skal være MÅLBAR. «Når vi får tid» er ikke en trigger,
og en midlertidig løsning med en slik trigger er permanent uten at noen
har bestemt seg for det.
"""
import os
import re

import pytest

MAPPE = os.path.join("docs", "beslutninger")

# MERK: at alle felter FINNES og at ingen seksjon er tom, voktes alt av
# `test_maalinger.test_hver_adr_fyller_hele_malen`. Den ble skrevet
# sammen med registeret (§29) og gjør jobben sin. Denne fila dupliserer
# den ikke — den prøver INNHOLDET i de feltene som lettest blir til
# tomme ord: eier, trigger, alternativer og status.

# Ord som gjør en «trigger» til en hensikt i stedet for en hendelse.
IKKE_MAALBART = ("når vi får tid", "ved behov", "senere", "etter hvert",
                 "når det passer", "på sikt")


def _adr_filer():
    return sorted(f for f in os.listdir(MAPPE)
                  if f.startswith("ADR-") and f.endswith(".md"))


def _tekst(navn):
    with open(os.path.join(MAPPE, navn), encoding="utf-8") as f:
        return f.read()


def _seksjon(tekst, overskrift):
    plass = tekst.index(f"## {overskrift}")
    neste = tekst.find("\n## ", plass + 1)
    return tekst[plass:neste if neste > 0 else len(tekst)]


def test_det_finnes_adr_er_i_det_hele_tatt():
    assert _adr_filer(), "ingen ADR-er — da er registeret en tom mappe"


@pytest.mark.parametrize("navn", _adr_filer())
def test_eieren_er_et_navn_ikke_en_rolle(navn):
    """En rolle kan ikke svare når triggeren slår inn. «Plattformteamet»
    leser ingen ADR."""
    blokk = _seksjon(_tekst(navn), "Owner").lower()
    kropp = blokk.split("\n", 1)[1][:250]
    # «Prosjekteier NAV dokument-AI» sto i seks ADR-er og slapp gjennom
    # en tidligere utgave av denne lista. En TITTEL er ikke et navn: den
    # som skal svare når triggeren slår inn, må kunne kontaktes.
    for rolle in ("teamet", "gruppen", "avdelingen", "plattformteam",
                  "utviklerne", "tbd", "ukjent", "prosjekteier",
                  "systemeier", "rollen"):
        assert rolle not in kropp, (
            f"{navn}: eieren ser ut som en rolle («{rolle}») — §29.1 "
            "krever en navngitt ansvarlig")


@pytest.mark.parametrize("navn", _adr_filer())
def test_review_trigger_er_maalbar(navn):
    blokk = _seksjon(_tekst(navn), "Review Trigger").lower()
    for frase in IKKE_MAALBART:
        assert frase not in blokk, (
            f"{navn}: «{frase}» er en hensikt, ikke en målbar hendelse "
            "(§29.1, og registerets egen regel 4)")


@pytest.mark.parametrize("navn", _adr_filer())
def test_review_date_er_en_dato(navn):
    """«Senest dato for vurdering, selv uten trigger» (§29.1). Uten en
    dato blir en midlertidig løsning permanent i stillhet."""
    blokk = _seksjon(_tekst(navn), "Review Date")
    assert re.search(r"\b20\d{2}-\d{2}-\d{2}\b", blokk), (
        f"{navn}: Review Date har ingen dato på formen ÅÅÅÅ-MM-DD")


@pytest.mark.parametrize("navn", _adr_filer())
def test_minst_ett_alternativ_ble_vurdert(navn):
    """Malen sier det rett ut: står det ingen alternativer, er dette
    ikke en beslutning — det er en beskrivelse av det som tilfeldigvis
    ble gjort."""
    blokk = _seksjon(_tekst(navn), "Alternatives Considered")
    assert re.search(r"^\s*(\d+\.|[-*])\s+\S", blokk, re.M), (
        f"{navn}: ingen opplistede alternativer")


@pytest.mark.parametrize("navn", _adr_filer())
def test_status_er_en_av_de_lovlige(navn):
    t = _tekst(navn)
    m = re.search(r"\*\*Status:\*\*\s*(.+)", t)
    assert m, f"{navn} mangler Status"
    status = m.group(1).strip().rstrip("*").strip()
    lovlige = ("Foreslått", "Gjeldende", "Midlertidig", "Lukket")
    assert status.startswith(lovlige) or status.startswith("Erstattet av"), (
        f"{navn}: ukjent status «{status}»")


def test_alle_adr_er_staar_i_registeret():
    """En ADR ingen finner, finnes ikke."""
    les_meg = _tekst("LES_MEG.md")
    for navn in _adr_filer():
        assert navn in les_meg, (
            f"{navn} står ikke i tabellen i LES_MEG.md")


def test_malen_selv_teller_ikke_som_en_beslutning():
    assert "MAL.md" not in _adr_filer()
