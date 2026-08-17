"""
Interaktive beholder reservert kapasitet under batch-burst (§26, ADR-0007).

Lasttesten viste at de ikke gjorde det (R210, 100 brukere):

    interaktiv: spørsmål   median 17 000 ms   p95 91 000 ms
    batch: 500 sider       median    210 ms   p95    720 ms

Omvendt av hva navnene antyder — og mekanismen forklarer hvorfor.
`POST /jobb` KØER bare arbeidet og svarer 202 med en gang. Det tunge
skjer i arbeidstråden etterpå, og den gikk helt UTENOM kapasitetsporten:
kommentaren i koden sa det rett ut, «/jobb er utelatt med vilje … har
allerede én arbeidstråd som grense». Én tråd er en grense på antall
tråder, ikke på hvor mye av maskinen de tar.

Så det var ikke at batch spiste interaktive PLASSER. Batch tok ingen
plass i det hele tatt, og konkurrerte fritt om CPU og GPU med dem som
sto i kø for en.

LØSNINGEN: TO TAK I ÉN PORT
Interaktivt får hele grensen. Batch får grensen minus den reserverte
andelen. Én port, to tak — ikke to låser, som ville kunnet låse
hverandre.

PLASSEN TAS PER SIDE
Ikke per jobb. Holdt arbeidstråden én plass i 40 minutter, ville
reservasjonen bare flyttet problemet: de interaktive ville ventet på en
plass som aldri ble ledig.
"""
import sys
import threading
import time

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import dokument_api as api


@pytest.fixture
def port(monkeypatch):
    """En port med en fast, kjent grense — ellers måler testen maskinen."""
    p = api._Kapasitetsport()
    monkeypatch.setattr(p, "_gjeldende", lambda: {"grense": 4, "binder": "test"})
    return p


# ------------------------------------------------------------------ #
#  Selve reservasjonen                                                #
# ------------------------------------------------------------------ #

def test_batch_naar_aldri_den_siste_plassen(port, monkeypatch):
    """Kjernen i ADR-0007. Med grense 4 og én reservert skal batch
    stoppe på 3 — og den fjerde plassen stå åpen for et menneske."""
    monkeypatch.setattr(api, "RESERVERT_INTERAKTIV", 1)
    assert port.ta(0.1, for_batch=True) is True     # 1
    assert port.ta(0.1, for_batch=True) is True     # 2
    assert port.ta(0.1, for_batch=True) is True     # 3
    assert port.ta(0.1, for_batch=True) is False, (
        "batch fikk den reserverte plassen — da er reservasjonen borte")


def test_interaktiv_faar_plassen_batch_ikke_fikk(port, monkeypatch):
    """Den samme situasjonen, sett fra den som venter foran skjermen."""
    monkeypatch.setattr(api, "RESERVERT_INTERAKTIV", 1)
    for _ in range(3):
        port.ta(0.1, for_batch=True)
    assert port.ta(0.1, for_batch=False) is True, (
        "interaktivt slapp ikke inn på plassen som var reservert for det")


def test_interaktivt_faar_hele_grensen(port, monkeypatch):
    monkeypatch.setattr(api, "RESERVERT_INTERAKTIV", 1)
    for i in range(4):
        assert port.ta(0.1, for_batch=False) is True, f"plass {i + 1}"
    assert port.ta(0.1, for_batch=False) is False


def test_batch_faar_alltid_minst_en_plass(port, monkeypatch):
    """Ellers stopper jobbene helt. En reservasjon som sulter batch i
    hjel er ikke en fordeling, den er en avstenging."""
    monkeypatch.setattr(api, "RESERVERT_INTERAKTIV", 99)
    assert port.ta(0.1, for_batch=True) is True


def test_reservasjonen_kan_ikke_settes_til_null(port, monkeypatch):
    """«En reservasjon på null er det samme som ingen reservasjon, og
    skal ikke kunne konfigureres fram ved et uhell» (ADR-0007)."""
    monkeypatch.setattr(api, "RESERVERT_INTERAKTIV", 0)
    for _ in range(3):
        port.ta(0.1, for_batch=True)
    assert port.ta(0.1, for_batch=True) is False, (
        "med RESERVERT_INTERAKTIV=0 tok batch hele grensen")


def test_plassen_frigjoeres_igjen(port, monkeypatch):
    monkeypatch.setattr(api, "RESERVERT_INTERAKTIV", 1)
    for _ in range(3):
        port.ta(0.1, for_batch=True)
    assert port.ta(0.1, for_batch=True) is False
    port.slipp()
    assert port.ta(0.1, for_batch=True) is True


def test_en_ventende_vekkes_naar_en_plass_blir_ledig(port, monkeypatch):
    """Uten `notify` ville den ventende stått til fristen løp ut, selv
    om plassen ble ledig med en gang."""
    monkeypatch.setattr(api, "RESERVERT_INTERAKTIV", 1)
    for _ in range(4):
        port.ta(0.1, for_batch=False)
    fikk = []

    def venter():
        fikk.append(port.ta(3.0, for_batch=False))

    t = threading.Thread(target=venter)
    t.start()
    time.sleep(0.2)
    port.slipp()
    t.join(timeout=4)
    assert fikk == [True]


# ------------------------------------------------------------------ #
#  Jobbarbeidet må faktisk gjennom porten                             #
# ------------------------------------------------------------------ #

def test_jobbarbeidet_tar_en_batchplass_PER_SIDE():
    """Per jobb ville vært verre enn ingenting: én plass holdt i 40
    minutter er en plass de interaktive aldri får."""
    import inspect
    kilde = inspect.getsource(api._jobb_arbeider)
    assert "_vent_paa_batchplass" in kilde
    assert "for_batch=True" in kilde
    plass_side = kilde.index("def _les_en_side(")
    plass_vent = kilde.index("_vent_paa_batchplass()", plass_side)
    plass_arbeid = kilde.index("_les_en_side_intern(i)", plass_side)
    assert plass_vent < plass_arbeid, (
        "sida leses før plassen er tatt — da er porten dekorasjon")


def test_plassen_slippes_selv_om_siden_feiler():
    """En side som kaster, må ikke ta plassen med seg i graven."""
    import inspect
    kilde = inspect.getsource(api._jobb_arbeider)
    plass = kilde.index("def _les_en_side(")
    blokk = kilde[plass:plass + 700]
    assert "finally:" in blokk and "_kapasitet_port.slipp()" in blokk


def test_avbrutt_jobb_venter_ikke_evig_paa_en_plass():
    """Ventingen har ingen frist utover avbrudd — da må avbruddet
    faktisk sjekkes, ellers henger en avbestilt jobb i køen."""
    import inspect
    kilde = inspect.getsource(api._jobb_arbeider)
    plass = kilde.index("def _vent_paa_batchplass")
    blokk = kilde[plass:plass + 900]
    assert 'jobb.get("avbrutt")' in blokk


# ------------------------------------------------------------------ #
#  Synlighet — ellers leses beslutningen som en regresjon             #
# ------------------------------------------------------------------ #

def test_fordelingen_er_synlig_i_status(port, monkeypatch):
    monkeypatch.setattr(api, "RESERVERT_INTERAKTIV", 1)
    s = port.status()
    assert s["grense"] == 4
    assert s["tak_batch"] == 3
    assert s["reservert_interaktiv"] == 1


def test_fordelingen_er_en_metrikk():
    """ADR-0007: en operatør som ser at batch går saktere enn maskinen
    tåler, skal finne svaret i /metrics — ikke i koden."""
    from delt import maalinger
    for navn in ("nav_reservert_interaktiv", "nav_tak_batch"):
        assert navn in maalinger._BESKRIVELSER, f"{navn} er ubeskrevet"
    import inspect
    assert "nav_tak_batch" in inspect.getsource(api)
