"""
Blandet dokument (R237): tekstlag på noen sider, skann på resten.

Feilen dette låser fast: OCR-terskelen gjaldt dokumentet SAMLET
(total_tekst < 20). En saksmappe med 19 tekstsider og 31 skannede fikk
aldri OCR — tekstlaget «beviste» at dokumentet var digitalt, de 31
sidene ble rapportert som blanke_sider, og 62 % av dokumentet var
stille ulest. Del-svaret så helt friskt ut: ok=true, ingen advarsel.

Nå gjelder terskelen per side: sidene uten tekstlag OCR-es og flettes
inn i sideorden, tekstlaget beholdes som fasit der det finnes, og
avkorting sies fra om. OCR-motoren mockes — testene låser flettingen
og rapporteringen, ikke lesekvaliteten.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz

from delt import region_ocr
from delt.dokumentprofil import blanke_sider


@pytest.fixture(scope="module")
def api():
    import dokument_api
    return dokument_api


@pytest.fixture
def falsk_ocr(monkeypatch):
    """Bytter ut region-OCR-en med en som alltid leser samme tekst —
    ocr_pdf_bytes kjører ekte (rendring, tomside-vakt, telling)."""
    monkeypatch.setattr(region_ocr, "ocr_side", lambda bilde: {
        "tekst": "OCR-LEST-INNHOLD",
        "regioner": [{"boks": [0, 0, 10, 10], "tekst": "OCR-LEST-INNHOLD",
                      "motor": "easyocr", "konfidens": 0.99,
                      "skrift": "trykk"}]})


def _tekstside(doc, innhold):
    side = doc.new_page(width=400, height=300)
    side.insert_text((30, 50), innhold)


def _skannside(doc):
    """Side uten tekstlag, men med nok «blekk» til å passere
    tomside-vakten — slik en skannet side ser ut for koden."""
    side = doc.new_page(width=400, height=300)
    side.draw_rect(fitz.Rect(40, 40, 360, 260), fill=(0, 0, 0))


def _blandet_pdf():
    doc = fitz.open()
    _tekstside(doc, "Dette er en tekstlagsside med god del innhold i seg")
    _skannside(doc)
    _tekstside(doc, "Tredje side har også et tekstlag med mye innhold")
    data = doc.tobytes()
    doc.close()
    return data


def test_blandet_dokument_far_ocr_paa_sidene_uten_tekstlag(api, falsk_ocr):
    r = api.analyser_bytes("blandet.pdf", _blandet_pdf(),
                           les_strekkoder=False)
    assert r["ok"]
    assert r["kilde"] == "tekstlag+regionocr"
    assert r["ocr_brukt"] is True
    assert r["ocr_sider_lest"] == 1
    assert r["ocr_sider_uten_tekstlag"] == 1


def test_flettingen_skjer_i_sideorden_og_beholder_tekstlaget(api, falsk_ocr):
    r = api.analyser_bytes("blandet.pdf", _blandet_pdf(),
                           les_strekkoder=False)
    # OCR-teksten står under RIKTIG sidemarkør …
    assert "[Side 2 av 3]\nOCR-LEST-INNHOLD" in r["tekst"]
    # … og tekstlaget er urørt på begge sider av den
    assert "tekstlagsside" in r["tekst"]
    assert "Tredje side" in r["tekst"]


def test_blanke_sider_lyver_ikke_lenger(api, falsk_ocr):
    """Før R237 var side 2 «blank» i dokumentprofilen — den var full av
    innhold som aldri ble lest."""
    r = api.analyser_bytes("blandet.pdf", _blandet_pdf(),
                           les_strekkoder=False)
    assert blanke_sider(r["tekst"]) == []


def test_avkorting_telles_i_ocr_sider_og_sies_fra_om(api, falsk_ocr):
    """maks_sider teller OCR-LESTE sider, ikke sideposisjoner — og et
    kutt skal alltid ut som advarsel, aldri skje i stillhet."""
    doc = fitz.open()
    _tekstside(doc, "Tekstlagsside nummer en med rikelig innhold her")
    _skannside(doc)
    _skannside(doc)
    data = doc.tobytes()
    doc.close()

    r = api.analyser_bytes("kutt.pdf", data, ocr_maks_sider=1,
                           les_strekkoder=False)
    assert r["ocr_sider_lest"] == 1
    assert r["ocr_sider_uten_tekstlag"] == 2
    assert "OCR leste 1 av 2 sider uten tekstlag" in (r["advarsel"] or "")
    assert "side 3" in r["advarsel"]        # HVILKEN side som står ulest


def test_helskannet_dokument_tar_samme_vei_som_foer(api, falsk_ocr):
    """Uten tekstlag noe sted skal ingenting være endret: hele
    dokumentet OCR-es under den gamle kilden."""
    doc = fitz.open()
    _skannside(doc)
    _skannside(doc)
    data = doc.tobytes()
    doc.close()

    r = api.analyser_bytes("skann.pdf", data, les_strekkoder=False)
    assert r["kilde"] == "regionocr+deterministisk"
    assert r["ocr_sider_lest"] == 2
    assert "ocr_sider_uten_tekstlag" not in r


def test_ekte_blank_side_forblir_blank(api, falsk_ocr):
    """Tomside-vakten består: en faktisk hvit side skal rapporteres som
    blank — ikke få påfunnet OCR-tekst."""
    doc = fitz.open()
    _tekstside(doc, "Tekstlagsside nummer en med rikelig innhold her")
    doc.new_page(width=400, height=300)      # helt hvit
    data = doc.tobytes()
    doc.close()

    r = api.analyser_bytes("blank.pdf", data, les_strekkoder=False)
    assert blanke_sider(r["tekst"]) == [2]
    assert "(nesten) tom" in (r["advarsel"] or "")


def test_rent_tekstdokument_er_helt_uberort(api, falsk_ocr):
    """Ingen sider uten tekstlag → ingen OCR, samme svarform som før."""
    doc = fitz.open()
    _tekstside(doc, "Bare tekstlag her, godt over terskelen for innhold")
    data = doc.tobytes()
    doc.close()

    r = api.analyser_bytes("tekst.pdf", data, les_strekkoder=False)
    assert r["kilde"] == "deterministisk_tekstlag"
    assert r["ocr_brukt"] is False
