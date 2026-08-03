"""
POST /forhandssjekk — kvalitetsdom FØR GPU-en brukes.

Poenget med endepunktet: et dårlig skann skal avvises på ~sekundet i
stedet for å koste 30 s GPU og gi søppeltekst. Aldri OCR, aldri modell.

Testene dekker de tre lagene hver for seg:
  1) målingene (andel_blekk, naturlig_dpi) — ren pikselmatte
  2) dommen (doem_forhandssjekk) — ren regel-logikk
  3) endepunktet ende-til-ende med små PDF-er bygget i testen

Handler-metoden kalles direkte uten socket (som test_api_forbedringer).
"""
import sys
import types

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import numpy as np
import pytest

import dokument_api as api
from delt.forbehandling import TOM_SIDE_BLEKK, andel_blekk


# ------------------------------------------------------------------ #
#  1) målingene                                                       #
# ------------------------------------------------------------------ #

def _hvit_side(h=800, w=600):
    return np.full((h, w, 3), 255, dtype=np.uint8)


def test_andel_blekk_hvit_side_er_null():
    assert andel_blekk(_hvit_side()) == 0.0


def test_andel_blekk_tekstside_over_terskel():
    """En side med noen tekstlinjer skal måle KLART over tom-terskelen."""
    side = _hvit_side()
    for y in (100, 200, 300, 400):          # fire «tekstlinjer»
        side[y:y + 12, 50:550] = 0
    assert andel_blekk(side) > TOM_SIDE_BLEKK * 10


def test_andel_blekk_kantskygge_teller_ikke():
    """Skannerens mørke kant langs papiret skal ikke gjøre en blank side
    til en side med innhold — de ytterste 5 % kuttes før måling."""
    side = _hvit_side()
    side[:, :20] = 0          # mørk stripe langs venstre kant (< 5 %)
    side[:8, :] = 0           # og øverst
    assert andel_blekk(side) < TOM_SIDE_BLEKK


def test_naturlig_dpi_og_ocr_skala_bruker_samme_regnestykke():
    """Vakt for uttrekket av naturlig_dpi fra ocr_skala (R51): dpi-en
    skal være NØYAKTIG bildebredde/sidebredde × 72, og renderskalaen
    skal aldri være finere enn bildets egen oppløsning."""
    fitz = pytest.importorskip("fitz")
    import cv2
    px = np.full((1100, 850, 3), 255, np.uint8)
    px[100:130, 100:700] = 0
    ok, png = cv2.imencode(".png", px)
    assert ok
    bildedoc = fitz.open(stream=png.tobytes(), filetype="png")
    pdf = fitz.open("pdf", bildedoc.convert_to_pdf())
    side = pdf[0]
    forventet = 850 / side.rect.width * 72          # bildets egen dpi
    dpi = api.naturlig_dpi(pdf, side)
    assert dpi == pytest.approx(forventet, abs=0.5)
    # renderskala = min(OCR_DPI, naturlig)/72, aldri under 1.0 (R51)
    m = api.ocr_skala(pdf, side)
    assert m.a == pytest.approx(
        min(api.OCR_DPI, max(dpi, 72.0)) / 72.0, abs=0.02)
    pdf.close()


def test_naturlig_dpi_er_none_for_tekstside():
    """En ren tekstside kan rendres vilkårlig fint — ingen egen dpi."""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    side = doc.new_page()
    side.insert_text((72, 100), "ren tekst")
    assert api.naturlig_dpi(doc, side) is None
    doc.close()


# ------------------------------------------------------------------ #
#  2) dommen                                                          #
# ------------------------------------------------------------------ #

def _side(tom=False, uleselig=False, advarsler=None):
    return {"tom": tom, "uleselig": uleselig, "advarsler": advarsler or []}


def test_dom_god_uten_advarsler():
    dom, _ = api.doem_forhandssjekk([_side(), _side()])
    assert dom == "god"


def test_dom_avvis_naar_alle_sider_er_tomme():
    dom, anbefaling = api.doem_forhandssjekk(
        [_side(tom=True, advarsler=["tom side"])] * 3)
    assert dom == "avvis"
    assert "tomme" in anbefaling


def test_dom_avvis_naar_alt_innhold_er_uleselig():
    dom, anbefaling = api.doem_forhandssjekk([
        _side(uleselig=True, advarsler=["uskarpt bilde"]),
        _side(tom=True, advarsler=["tom side"]),
    ])
    assert dom == "avvis"
    assert "oppløsning" in anbefaling or "uleselige" in anbefaling


def test_dom_tvilsom_ved_advarsel():
    dom, _ = api.doem_forhandssjekk([_side(advarsler=["for mørkt bilde"]),
                                     _side()])
    assert dom == "tvilsom"


def test_blank_bakside_gir_ikke_avvis():
    """Tosidig skanning legger rutinemessig inn blanke baksider — én tom
    side blant innholdssider er normalt, ikke en feil. Men den skal
    heller ikke forties: dommen er «tvilsom», ikke «god»."""
    dom, _ = api.doem_forhandssjekk([
        _side(),
        _side(tom=True, advarsler=["tom side"]),
        _side(),
    ])
    assert dom == "tvilsom"


def test_en_uleselig_side_blant_gode_er_tvilsom():
    dom, _ = api.doem_forhandssjekk([
        _side(uleselig=True, advarsler=["uskarpt bilde"]),
        _side(),
    ])
    assert dom == "tvilsom"


# ------------------------------------------------------------------ #
#  3) endepunktet                                                     #
# ------------------------------------------------------------------ #

def _fang_handler():
    h = api.Handler.__new__(api.Handler)
    h.headers = {}
    h.path = "/forhandssjekk"
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


def _tekst_pdf() -> bytes:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    side = doc.new_page()
    side.insert_text((72, 100), "Kvittering for taxitur — Total Kr: 486,00")
    data = doc.tobytes()
    doc.close()
    return data


def _blank_bilde_pdf(sider=2) -> bytes:
    fitz = pytest.importorskip("fitz")
    import cv2
    px = np.full((1100, 850, 3), 255, np.uint8)
    ok, png = cv2.imencode(".png", px)
    assert ok
    ut = fitz.open()
    for _ in range(sider):
        bildedoc = fitz.open(stream=png.tobytes(), filetype="png")
        ut.insert_pdf(fitz.open("pdf", bildedoc.convert_to_pdf()))
    data = ut.tobytes()
    ut.close()
    return data


def test_tekstlag_gir_god_uten_sidevurdering():
    h, fanget = _fang_handler()
    h._forhandssjekk("brev.pdf", "pdf", _tekst_pdf(), {})
    assert fanget["kode"] == 200
    svar = fanget["kropp"]
    assert svar["dom"] == "god"
    assert svar["tekstlag"] is True
    assert svar["trenger_ocr"] is False
    assert svar["sider"] == []
    assert "tekstlag" in svar["anbefaling"]


def test_blanke_bildesider_avvises():
    h, fanget = _fang_handler()
    h._forhandssjekk("skann.pdf", "pdf", _blank_bilde_pdf(), {})
    assert fanget["kode"] == 200
    svar = fanget["kropp"]
    assert svar["tekstlag"] is False
    assert svar["dom"] == "avvis"
    assert all(s["tom"] for s in svar["sider"])
    assert svar["sider"][0]["blekk_andel"] < TOM_SIDE_BLEKK


def _skarpt_bilde_pdf() -> bytes:
    """Knivskarpt 1700×2200-«skann» med tydelig tekst, lastet opp som
    PNG → nominell dpi blir 96 (formatets antakelse)."""
    fitz = pytest.importorskip("fitz")
    import cv2
    px = np.full((2200, 1700, 3), 255, np.uint8)
    for y in range(200, 2000, 90):
        cv2.putText(px, "Kvittering for taxitur - Total Kr: 486,00",
                    (100, y), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3)
    ok, png = cv2.imencode(".png", px)
    assert ok
    bildedoc = fitz.open(stream=png.tobytes(), filetype="png")
    return fitz.open("pdf", bildedoc.convert_to_pdf()).tobytes()


def test_skarpt_bilde_med_lav_nominell_dpi_er_god():
    """Kalibreringsfunnet som endret dømmingen: et knivskarpt bilde med
    nok piksler fikk «avvis» fordi nominell dpi var 96 — men den dpi-en
    er PNG-formatets antakelse, ikke en egenskap ved bildet. En
    dpi-terskel ville avvist hvert eneste mobilfoto uansett kvalitet.
    Dømmingen skal skje på rendrede piksler."""
    h, fanget = _fang_handler()
    h._forhandssjekk("skann.pdf", "pdf", _skarpt_bilde_pdf(), {})
    svar = fanget["kropp"]
    assert svar["sider"][0]["dpi"] == pytest.approx(96, abs=2)
    assert svar["sider"][0]["uleselig"] is False
    assert svar["dom"] == "god", (
        "skarpt bilde med nok piksler skal ikke avvises pga. nominell dpi: "
        + str(svar["sider"][0]))


def test_altfor_faa_piksler_avvises():
    """Motstykket: et bittelite bilde (200×260) har for få piksler til at
    tekst kan leses — uansett hvor «skarpt» det er."""
    fitz = pytest.importorskip("fitz")
    import cv2
    px = np.full((260, 200, 3), 255, np.uint8)
    cv2.putText(px, "NAV", (30, 130), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    ok, png = cv2.imencode(".png", px)
    assert ok
    bildedoc = fitz.open(stream=png.tobytes(), filetype="png")
    data = fitz.open("pdf", bildedoc.convert_to_pdf()).tobytes()
    h, fanget = _fang_handler()
    h._forhandssjekk("frimerke.pdf", "pdf", data, {})
    svar = fanget["kropp"]
    assert svar["sider"][0]["uleselig"] is True
    assert svar["dom"] == "avvis"
    assert any("piksler" in a for a in svar["sider"][0]["advarsler"])


def test_korrupt_pdf_gir_400():
    h, fanget = _fang_handler()
    h._forhandssjekk("rot.pdf", "pdf", b"ikke en pdf i det hele tatt", {})
    assert fanget["kode"] == 400
    assert "PDF" in fanget["kropp"]["feil"]


def test_tekstdokument_har_ikke_noe_skann():
    h, fanget = _fang_handler()
    h._forhandssjekk("notat.txt", "tekst", "ren tekst her", {})
    assert fanget["kode"] == 200
    assert fanget["kropp"]["dom"] == "god"
    assert fanget["kropp"]["sider_vurdert"] == 0


def test_ukjent_felt_meldes_ogsaa_her():
    """Samme løfte som resten av API-et: et ukjent feltnavn forsvinner
    aldri i stillhet."""
    h, fanget = _fang_handler()
    h._forhandssjekk("brev.pdf", "pdf", _tekst_pdf(), {"max_pages": "3"})
    assert fanget["kode"] == 200
    assert any("max_pages" in a for a in fanget["kropp"]["advarsler"])


def test_maks_sider_respekteres():
    h, fanget = _fang_handler()
    h._forhandssjekk("skann.pdf", "pdf", _blank_bilde_pdf(sider=3),
                     {"maks_sider": "1"})
    svar = fanget["kropp"]
    assert svar["sider_vurdert"] == 1
    assert svar["antall_sider"] == 3
    assert any("1 av 3" in a for a in svar["advarsler"])


def test_verdi_som_feltnavn_gir_400():
    h, fanget = _fang_handler()
    h._forhandssjekk("brev.pdf", "pdf", _tekst_pdf(), {"ja": "maks_sider"})
    assert fanget["kode"] == 400


# ------------------------------------------------------------------ #
#  Tomside-vakten i selve OCR-løpet (gjenbruker andel_blekk)           #
# ------------------------------------------------------------------ #

def test_ocr_hopper_over_blanke_sider_uten_aa_dikte():
    """Målt på en ekte skannet bunke: en nesten blank side (blekkandel
    0,00064 — gjennomslag fra arket bak) fikk OCR til å «lese» to
    linjer som ikke finnes. Vakten skal rapportere siden som tom i
    stedet — og fordi ocr_side aldri kalles for blanke sider, trenger
    testen ingen OCR-motorer."""
    fitz = pytest.importorskip("fitz")
    import cv2
    px = np.full((1100, 850, 3), 255, np.uint8)
    ok, png = cv2.imencode(".png", px)
    assert ok
    ut = fitz.open()
    for _ in range(2):
        b = fitz.open(stream=png.tobytes(), filetype="png")
        ut.insert_pdf(fitz.open("pdf", b.convert_to_pdf()))
    data = ut.tobytes()
    ut.close()
    res = api.ocr_pdf_bytes(data)
    assert res["tomme_sider"] == [1, 2]
    # Bare paginermerkene igjen — ikke ett dikta ord
    innhold = [l for l in res["tekst"].splitlines()
               if l.strip() and not l.startswith("[Side ")]
    assert innhold == []
    assert res["motorer"] == {}          # ingen motor ble noensinne kalt
    assert [s["regioner"] for s in res["_sider_regioner"]] == [[], []]
