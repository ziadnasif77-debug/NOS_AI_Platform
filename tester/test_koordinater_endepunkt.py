"""
Bryteren koordinater=ja på POST /dokument.

Tekstlagsveien testes ende-til-ende (ingen OCR, ingen GPU): en liten
PDF med tekstlag → /dokument-handleren → koordinater med bokser i
PDF-punkter. OCR-veien er dekket av enhetstestene på delt/koordinater
(samme kjede med syntetiske regioner) og verifiseres mot kjørende
server med korpusdokumentene.
"""
import sys
import types

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import dokument_api as api


def _fang_handler():
    h = api.Handler.__new__(api.Handler)
    h.headers = {}
    h.path = "/dokument"
    h.command = "POST"
    h.client_address = ("127.0.0.1", 4321)
    fanget = {}
    h.send_response = lambda k: fanget.__setitem__("kode", k)
    h.send_header = lambda n, v: None
    h.end_headers = lambda: None
    h.wfile = types.SimpleNamespace(
        write=lambda b: fanget.__setitem__(
            "kropp", __import__("json").loads(b)))
    h._cors_origin = lambda: None
    return h, fanget


def _tekstlag_pdf() -> bytes:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    side = doc.new_page()
    side.insert_text((72, 100), "Kvittering — Org. Nr: 889 000 007")
    side.insert_text((72, 140), "Telefon: 22 33 44 55 — Total Kr: 486,00")
    data = doc.tobytes()
    doc.close()
    return data


def test_uten_bryteren_er_koordinater_null():
    h, fanget = _fang_handler()
    h._dokument_samlet("brev.pdf", "pdf", _tekstlag_pdf(), None, {}, True)
    assert fanget["kode"] == 200
    assert fanget["kropp"]["koordinater"] is None


def test_tekstlagsvei_gir_bokser_i_pdf_punkter():
    h, fanget = _fang_handler()
    h._dokument_samlet("brev.pdf", "pdf", _tekstlag_pdf(), None,
                       {"koordinater": "ja"}, True)
    assert fanget["kode"] == 200
    k = fanget["kropp"]["koordinater"]
    assert k is not None
    assert k["koordinatrom"] == "pdf_punkter"
    assert k["antall_funn"] >= 2
    side1 = k["sider"][0]
    assert side1["side"] == 1
    assert side1["bredde"] > 0 and side1["hoyde"] > 0
    typer = {f["type"]: f for f in side1["funn"]}
    assert "organisasjonsnummer" in typer
    assert "telefon" in typer
    for boks in typer["organisasjonsnummer"]["bokser"]:
        x0, y0, x1, y1 = boks
        assert 0 <= x0 < x1 <= side1["bredde"]
        assert 0 <= y0 < y1 <= side1["hoyde"]


def test_funnene_stemmer_med_felter_delen():
    """Koordinatfunnene og felter-delen bruker samme finnere — de skal
    aldri være uenige om orgnr-et."""
    h, fanget = _fang_handler()
    h._dokument_samlet("brev.pdf", "pdf", _tekstlag_pdf(), None,
                       {"koordinater": "ja"}, True)
    kropp = fanget["kropp"]
    orgnr_felter = kropp["felter"]["felter"]["organisasjonsnummer"]
    funn = [f for s in kropp["koordinater"]["sider"] for f in s["funn"]
            if f["type"] == "organisasjonsnummer"]
    assert len(funn) == 1
    assert funn[0]["tekst"].replace(" ", "") == orgnr_felter


def test_ren_tekst_har_ingen_koordinater_og_sier_det():
    h, fanget = _fang_handler()
    h._dokument_samlet("notat.txt", "tekst",
                       "Org. Nr: 889 000 007", None, {"koordinater": "ja"}, True)
    kropp = fanget["kropp"]
    assert kropp["koordinater"] is None
    assert any("koordinater" in a for a in kropp["kvalitet"]["advarsler"])


def test_ukjent_bryterverdi_gir_400():
    h, fanget = _fang_handler()
    h._dokument_samlet("brev.pdf", "pdf", _tekstlag_pdf(), None,
                       {"koordinater": "kanskje"}, True)
    assert fanget["kode"] == 400


def test_koordinater_er_dokumentert_i_openapi():
    spekk = api._openapi()
    assert "KoordinatDel" in spekk["components"]["schemas"]
    assert "KoordinatFunn" in spekk["components"]["schemas"]
    dok = spekk["paths"]["/dokument"]["post"]
    egenskaper = dok["requestBody"]["content"]["multipart/form-data"][
        "schema"]["properties"]
    assert "koordinater" in egenskaper
