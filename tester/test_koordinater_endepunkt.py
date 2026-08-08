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


# ------------------------------------------------------------------ #
#  Boksene gjelder et bilde klienten ikke har fått (R167)              #
# ------------------------------------------------------------------ #
#
# `koordinatrom` het «forbehandlet_bilde_piksler», og dokumentasjonen
# sa at sidedimensjonene følger med «så en utheving kan skaleres
# riktig». Det er sant for `pdf_punkter` og for OCR-sider som IKKE ble
# geometrisk rettet — ikke ellers.
#
# Målt: 3 graders skjevhetsretting flytter et punkt opptil 31,6 piksler,
# og forskyvningen avhenger av HVOR punktet ligger. Perspektivretting
# endrer i tillegg dimensjonene (1400×1100 → 1183×864). Ingen ensartet
# skalering retter det opp — og klienten fikk aldri vite det.
#
# `bildekvalitet` gjorde det verre: den var side 1s rapport for HELE
# dokumentet, så en klient som ville regne selv hadde ikke engang
# vinkelen for side 2.

from delt.koordinater import koordinater_for_sider


def _side(nr, skjev=0.0, perspektiv=False):
    return {"side": nr, "bredde": 800, "hoyde": 1000, "regioner": [],
            "forbehandling": {"skjevhet_grader": skjev,
                              "perspektiv_rettet": perspektiv}}


def test_urort_side_kan_kartlegges():
    svar = koordinater_for_sider([_side(1)], "forbehandlet_bilde_piksler")
    assert svar["kan_kartlegges_til_original"] is True
    assert svar["sider"][0]["kan_kartlegges_til_original"] is True


def test_skjevhetsrettet_side_kan_IKKE_kartlegges():
    svar = koordinater_for_sider([_side(1, skjev=-3.0)],
                                 "forbehandlet_bilde_piksler")
    assert svar["kan_kartlegges_til_original"] is False
    assert svar["sider"][0]["skjevhet_grader"] == -3.0


def test_perspektivrettet_side_kan_IKKE_kartlegges():
    svar = koordinater_for_sider([_side(1, perspektiv=True)],
                                 "forbehandlet_bilde_piksler")
    assert svar["kan_kartlegges_til_original"] is False


def test_en_rettet_side_smitter_paa_hele_svaret():
    """Dokumentflagget er en OG av sidene: kan én side ikke kartlegges,
    kan ikke klienten tegne uten å se etter per side."""
    svar = koordinater_for_sider([_side(1), _side(2, skjev=-3.0)],
                                 "forbehandlet_bilde_piksler")
    assert svar["kan_kartlegges_til_original"] is False
    assert svar["sider"][0]["kan_kartlegges_til_original"] is True
    assert svar["sider"][1]["kan_kartlegges_til_original"] is False


def test_vinkelen_oppgis_PER_SIDE():
    """`bildekvalitet` bar side 1s tall for hele dokumentet. En side 3
    som er skjev 4 grader ble meldt som 0.0."""
    svar = koordinater_for_sider(
        [_side(1), _side(2, skjev=-4.0), _side(3)],
        "forbehandlet_bilde_piksler")
    assert [s["skjevhet_grader"] for s in svar["sider"]] == [0.0, -4.0, 0.0]


def test_dokumentasjonen_sier_det_ogsaa():
    """Feltet hjelper ikke hvis dokumentet fortsatt lover det motsatte."""
    import os
    rot = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tekst = open(os.path.join(rot, "docs", "endepunkter.md"),
                 encoding="utf-8").read()
    assert "kan_kartlegges_til_original" in tekst
    assert "31,6" in tekst, "målingen som viser hvorfor, mangler"
