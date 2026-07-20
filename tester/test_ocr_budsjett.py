"""
Tester for R52: taket på håndskriftmodellen (norhand) i
delt/region_ocr.py.

Bakgrunnen er en ekte regresjon: norhand ble kalt for HVER region der
EasyOCR var usikker, uten øvre grense. På et virkelig dokument ga det 34
kall à 3,7 s på CPU — 53 sekunder for ett bilde. To ting skal hindre at
det skjer igjen, og begge testes her:

  1) norhand kalles bare når regionen faktisk ligner håndskrift (eller
     EasyOCR har gitt helt opp) — ikke bare fordi konfidensen er lav
  2) det finnes et hardt tak, både på antall kall og på tid brukt

Testene stubber ut motorene, så de kjører uten GPU, uten modellfiler og
på millisekunder.
"""
import sys

sys.path.insert(0, ".")

import numpy as np
import pytest

from delt import region_ocr


@pytest.fixture
def stubbet(monkeypatch):
    """Bytter ut håndskriftmodellen med en tellende stubb.

    Returnerer en dict der 'norhand' teller hvor mange REGIONER som ble
    sendt til modellen. Regionene leses porsjonsvis (R55), så antall
    modellkall er ikke det interessante — antall regioner er.
    """
    teller = {"norhand": 0}

    def falsk_batch(utsnitt_liste):
        teller["norhand"] += len(utsnitt_liste)
        return [("handskrevet tekst", 0.90) for _ in utsnitt_liste]

    monkeypatch.setattr(region_ocr, "_norhand_les_batch", falsk_batch)
    # Ingen ekte GPU-lås eller cache-tømming i testen
    monkeypatch.setattr(region_ocr, "frigjor_gpu", lambda: None)
    monkeypatch.setattr(region_ocr, "_paa_gpu", lambda: False)
    return teller


def _regioner(antall: int, konfidens: float, tekst: str = None):
    """Lager `antall` syntetiske EasyOCR-funn med gitt konfidens.
    Boksene er brede nok til at norhand er aktuell (>= 8 piksler).

    Standardteksten er bevisst UTEN sifre: velg_motor beskytter regioner
    med tall mot norhand (den leser ofte sifre feil), og det ville
    skjult hva disse testene faktisk måler.
    """
    funn = []
    for i in range(antall):
        y = 10 + i * 30
        boks = [[20, y], [400, y], [400, y + 20], [20, y + 20]]
        funn.append((boks, tekst if tekst is not None else "underskrift her", konfidens))
    return funn


def test_trykt_tekst_utloser_ikke_handskriftmodellen(stubbet, monkeypatch):
    """Lav konfidens alene er IKKE nok: ser regionen trykt ut, skal den
    dyre håndskriftmodellen ikke røres. Dette er selve regresjonen —
    før R52 kostet hver slik region 3,7 s på CPU til ingen nytte."""
    monkeypatch.setattr(region_ocr, "_les_regioner",
                        lambda _b: _regioner(20, konfidens=0.40))
    monkeypatch.setattr(region_ocr, "_skriftslag", lambda *_: "trykt")

    bilde = np.full((700, 500, 3), 255, dtype=np.uint8)
    region_ocr.ocr_side(bilde)

    assert stubbet["norhand"] == 0


def test_handskrift_utloser_modellen(stubbet, monkeypatch):
    """Ser regionen håndskrevet ut og EasyOCR er usikker, SKAL norhand
    prøves — taket må ikke ha slått av funksjonaliteten."""
    monkeypatch.setattr(region_ocr, "_les_regioner",
                        lambda _b: _regioner(3, konfidens=0.40))
    monkeypatch.setattr(region_ocr, "_skriftslag", lambda *_: "handskrift")

    bilde = np.full((700, 500, 3), 255, dtype=np.uint8)
    res = region_ocr.ocr_side(bilde)

    assert stubbet["norhand"] == 3
    assert all(r["motor"] == "norhand" for r in res["regioner"])
    assert all(r["skrift"] == "handskrift" for r in res["regioner"])


def test_tall_beskyttes_mot_norhand(stubbet, monkeypatch):
    """Regioner med sifre (beløp, datoer, fødselsnummer) skal beholde
    EasyOCR-lesningen selv når norhand svarer med høy konfidens —
    norhand er trent på historisk håndskrift og bommer ofte på tall.
    Modellen får gjerne prøve; den skal bare ikke vinne."""
    monkeypatch.setattr(region_ocr, "_les_regioner",
                        lambda _b: _regioner(2, konfidens=0.40,
                                             tekst="Belop 12 500 kroner"))
    monkeypatch.setattr(region_ocr, "_skriftslag", lambda *_: "handskrift")

    bilde = np.full((700, 500, 3), 255, dtype=np.uint8)
    res = region_ocr.ocr_side(bilde)

    assert all(r["motor"] == "easyocr" for r in res["regioner"])
    assert all("12 500" in r["tekst"] for r in res["regioner"])


def test_antallstaket_holder(stubbet, monkeypatch):
    """Selv om HVER region ser håndskrevet ut, skal antall kall aldri
    overstige MAKS_NORHAND_PER_SIDE."""
    antall = region_ocr.MAKS_NORHAND_PER_SIDE + 25
    monkeypatch.setattr(region_ocr, "_les_regioner",
                        lambda _b: _regioner(antall, konfidens=0.40))
    monkeypatch.setattr(region_ocr, "_skriftslag", lambda *_: "handskrift")

    bilde = np.full((antall * 30 + 60, 500, 3), 255, dtype=np.uint8)
    region_ocr.ocr_side(bilde)

    assert stubbet["norhand"] == region_ocr.MAKS_NORHAND_PER_SIDE


def test_tidstaket_holder(monkeypatch):
    """Er modellen treg (som på CPU), skal tidsbudsjettet stoppe videre
    porsjoner — ellers skalerer svartiden med antall regioner."""
    teller = {"regioner": 0, "porsjoner": 0}
    klokke = {"na": 0.0}

    def treg_batch(utsnitt_liste):
        teller["porsjoner"] += 1
        teller["regioner"] += len(utsnitt_liste)
        klokke["na"] += 3.7 * len(utsnitt_liste)     # CPU-takt, målt
        return [("tekst", 0.90) for _ in utsnitt_liste]

    monkeypatch.setattr(region_ocr, "_norhand_les_batch", treg_batch)
    monkeypatch.setattr(region_ocr, "frigjor_gpu", lambda: None)
    monkeypatch.setattr(region_ocr, "_paa_gpu", lambda: False)
    monkeypatch.setattr(region_ocr.time, "perf_counter", lambda: klokke["na"])
    monkeypatch.setattr(region_ocr, "NORHAND_BATCH", 2)
    monkeypatch.setattr(region_ocr, "_les_regioner",
                        lambda _b: _regioner(30, konfidens=0.40))
    monkeypatch.setattr(region_ocr, "_skriftslag", lambda *_: "handskrift")

    bilde = np.full((1000, 500, 3), 255, dtype=np.uint8)
    region_ocr.ocr_side(bilde)

    # Budsjettet sjekkes FØR hver porsjon, så den siste kan krysse
    # grensen: det avgjørende er at det STOPPER, ikke at det treffer
    # eksakt. Uten taket ville alle 12 kandidatene blitt lest.
    assert teller["porsjoner"] == 1
    assert teller["regioner"] < region_ocr.MAKS_NORHAND_PER_SIDE


def test_oppgitt_easyocr_prover_norhand_uansett(stubbet, monkeypatch):
    """Har EasyOCR gitt helt opp (konfidens under TERSKEL_OPPGITT), sier
    den visuelle testen ingenting — den bygger på den utleste teksten.
    Da skal norhand prøves selv om regionen ser trykt ut."""
    monkeypatch.setattr(region_ocr, "_les_regioner",
                        lambda _b: _regioner(2, konfidens=0.10))
    monkeypatch.setattr(region_ocr, "_skriftslag", lambda *_: "trykt")

    bilde = np.full((700, 500, 3), 255, dtype=np.uint8)
    region_ocr.ocr_side(bilde)

    assert stubbet["norhand"] == 2


def test_hoy_konfidens_rorer_aldri_norhand(stubbet, monkeypatch):
    """Er EasyOCR trygg, skal norhand aldri kalles — uansett hvordan
    regionen ser ut."""
    monkeypatch.setattr(region_ocr, "_les_regioner",
                        lambda _b: _regioner(10, konfidens=0.95))
    monkeypatch.setattr(region_ocr, "_skriftslag", lambda *_: "handskrift")

    bilde = np.full((700, 500, 3), 255, dtype=np.uint8)
    region_ocr.ocr_side(bilde)

    assert stubbet["norhand"] == 0
