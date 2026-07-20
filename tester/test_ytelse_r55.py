"""
Tester for R55 — tre ytelsestiltak som alle skal virke UTEN å endre hva
systemet svarer:

  1) håndskriftmodellen leser flere regioner i samme kall (porsjonsvis)
  2) strekkodelesingen gjenbruker sidebildene OCR alt har rendret
  3) strekkodelesingen kan slås av per forespørsel

Testene sjekker atferden, ikke tidtakingen: en test som måler sekunder
blir flaky på en maskin under last. Det som SKAL være låst, er at
gjenbruk og porsjonering gir nøyaktig samme resultat som før.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import numpy as np
import pytest

from delt import region_ocr


# ------------------------------------------------------------------ #
#  1) Porsjonsvis lesing med håndskriftmodellen                       #
# ------------------------------------------------------------------ #

def _regioner(antall: int, konfidens: float, tekst: str = "underskrift her"):
    funn = []
    for i in range(antall):
        y = 10 + i * 30
        funn.append(([[20, y], [400, y], [400, y + 20], [20, y + 20]],
                     tekst, konfidens))
    return funn


@pytest.fixture
def stubb(monkeypatch):
    """Registrerer hver porsjon som sendes til håndskriftmodellen."""
    porsjoner = []

    def falsk_batch(utsnitt_liste):
        porsjoner.append(len(utsnitt_liste))
        return [("lest av norhand", 0.90) for _ in utsnitt_liste]

    monkeypatch.setattr(region_ocr, "_norhand_les_batch", falsk_batch)
    monkeypatch.setattr(region_ocr, "frigjor_gpu", lambda: None)
    monkeypatch.setattr(region_ocr, "_paa_gpu", lambda: False)
    monkeypatch.setattr(region_ocr, "_skriftslag", lambda *_: "handskrift")
    return porsjoner


def test_regioner_leses_samlet_ikke_en_og_en(stubb, monkeypatch):
    """Selve tiltaket: åtte kandidatregioner skal bli ETT modellkall, ikke
    åtte. Ett kall per region ga 26,7 % GPU-utnyttelse fordi kortet sto
    og ventet mellom hver bittelille kjerne."""
    monkeypatch.setattr(region_ocr, "NORHAND_BATCH", 8)
    monkeypatch.setattr(region_ocr, "_les_regioner",
                        lambda _b: _regioner(8, konfidens=0.40))

    region_ocr.ocr_side(np.full((400, 500, 3), 255, dtype=np.uint8))

    assert stubb == [8]


def test_porsjonene_folger_batchstorrelsen(stubb, monkeypatch):
    """Flere kandidater enn én porsjon rommer skal deles opp — det er
    delingen som lar tidstaket gripe inn underveis."""
    monkeypatch.setattr(region_ocr, "NORHAND_BATCH", 4)
    monkeypatch.setattr(region_ocr, "MAKS_NORHAND_PER_SIDE", 10)
    monkeypatch.setattr(region_ocr, "_les_regioner",
                        lambda _b: _regioner(10, konfidens=0.40))

    region_ocr.ocr_side(np.full((400, 500, 3), 255, dtype=np.uint8))

    assert stubb == [4, 4, 2]
    assert sum(stubb) == 10


def test_resultatet_er_uendret_av_porsjonering(stubb, monkeypatch):
    """Gevinsten skal være ren fart: hver region får fortsatt sitt eget
    svar, i riktig rekkefølge, med norhand som vinnende motor."""
    monkeypatch.setattr(region_ocr, "NORHAND_BATCH", 3)
    monkeypatch.setattr(region_ocr, "_les_regioner",
                        lambda _b: _regioner(5, konfidens=0.40))

    res = region_ocr.ocr_side(np.full((400, 500, 3), 255, dtype=np.uint8))

    assert len(res["regioner"]) == 5
    for r in res["regioner"]:
        assert r["motor"] == "norhand"
        assert r["tekst"] == "lest av norhand"
        assert r["norhand_konfidens"] == 0.9
        assert r["easyocr_tekst"] == "underskrift her"


# ------------------------------------------------------------------ #
#  2) og 3) Strekkoder: gjenbruk av sidebilder, og avskruing           #
# ------------------------------------------------------------------ #

@pytest.fixture(scope="module")
def api():
    import dokument_api
    return dokument_api


def test_strekkoder_gjenbruker_rendrede_sider(api, monkeypatch):
    """Får funksjonen ferdige sidebilder, skal den IKKE åpne og rendre
    dokumentet på nytt. Det var dobbeltarbeidet R55 fjernet."""
    aapnet = {"n": 0}
    import fitz

    def spion(*a, **kw):
        aapnet["n"] += 1
        raise AssertionError("dokumentet ble rendret på nytt")

    monkeypatch.setattr(fitz, "open", spion)
    sider = [np.full((40, 60, 3), 255, dtype=np.uint8)]

    koder = api.les_strekkoder_bytes(b"ikke-en-ekte-pdf", sider=sider)

    assert koder == []
    assert aapnet["n"] == 0


def test_strekkoder_kan_slaas_av(api, monkeypatch):
    """strekkoder=nei skal hoppe over skanningen helt — ikke bare
    forkaste resultatet etterpå."""
    kalt = {"n": 0}

    def spion(*a, **kw):
        kalt["n"] += 1
        return []

    monkeypatch.setattr(api, "les_strekkoder_bytes", spion)
    # Tom PDF holder: vi måler bare om skanningen ble forsøkt
    tom_pdf = __import__("fitz").open()
    tom_pdf.new_page(width=200, height=200)
    data = tom_pdf.tobytes()
    tom_pdf.close()

    api.analyser_bytes("a.pdf", data, les_strekkoder=False)
    assert kalt["n"] == 0

    api.analyser_bytes("b.pdf", data, les_strekkoder=True)
    assert kalt["n"] == 1


def test_cachen_skiller_paa_strekkodevalget(api):
    """To forespørsler på samme fil, én med og én uten strekkoder, må
    ikke servere hverandres resultat."""
    tom_pdf = __import__("fitz").open()
    s = tom_pdf.new_page(width=200, height=200)
    s.insert_text((20, 40), "Testdokument med litt tekst i seg")
    data = tom_pdf.tobytes()
    tom_pdf.close()

    uten = api.analyser_med_cache("x.pdf", data, les_strekkoder=False)
    med = api.analyser_med_cache("x.pdf", data, les_strekkoder=True)

    # Den andre skal IKKE komme fra cachen til den første
    assert med.get("fra_cache") is not True
    assert uten.get("ok") and med.get("ok")
