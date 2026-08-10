"""POST /spor med fil og et EKTE spørsmål — hovedveien inn i ruta.

Denne veien var DØD (R182). Kallet til `svar_paa_sporsmal` sendte
`skanning_kjorte`, et navn som bare finnes som lokal variabel i
`_les_dokument` — en helt annen metode. Hver eneste forespørsel med fil
og spørsmål traff `NameError` og ble 500:

    File "skript\\dokument_api.py", line 6660, in _do_post_intern
        skanning_kjorte)
    NameError: name 'skanning_kjorte' is not defined

Og 1590 tester var grønne. Hullet var ikke tilfeldig:

  test_spor_formstabilitet   tester `_spor_svar()` — SVARBYGGEREN, ikke
                             ruta. Den passerer aldri linja som krasjet.
  test_multipart_usitert…    tester `_parse_multipart` — PARSEREN.
  resten                     kaller `_dokument_samlet` direkte.

Ingen test kjørte `_do_post_intern` for /spor. Ruta med flest brukere
var den eneste uten dekning, og feilen var ikke subtil — den var 100 %
reproduserbar på første forsøk.

Derfor kjører testene her ruta HELE VEIEN, fra multipart-kroppen til
svaret. Modellen er byttet ut med en stubb (ingen GPU, ingen Borealis),
men det stopper ikke vakten: Python regner ut ALLE argumentene før
kallet, så et udefinert navn i argumentlista smeller uansett hva som
står i den andre enden.

I tillegg kontrolleres at `strekkoder_lest` er ÆRLIG i alle tre
grenene — det var hele poenget med R159, og den grenen som krasjet var
også den som skulle bære flagget.
"""
import io
import sys
import types

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import dokument_api as api

GRENSE = "----vakt182"


def _kropp(filnavn: bytes, fildata: bytes, **felt) -> bytes:
    """Bygger en ekte multipart-kropp — samme form som en klient sender."""
    deler = []
    if filnavn is not None:
        deler.append(
            b'Content-Disposition: form-data; name="fil"; filename="'
            + filnavn + b'"\r\nContent-Type: application/octet-stream'
            b"\r\n\r\n" + fildata)
    for navn, verdi in felt.items():
        deler.append(
            b'Content-Disposition: form-data; name="' + navn.encode()
            + b'"\r\n\r\n' + verdi.encode())
    ut = b""
    for d in deler:
        ut += b"--" + GRENSE.encode() + b"\r\n" + d + b"\r\n"
    return ut + b"--" + GRENSE.encode() + b"--\r\n"


def _handler(kropp: bytes):
    h = api.Handler.__new__(api.Handler)
    h.path = "/spor"
    h.command = "POST"
    h.client_address = ("127.0.0.1", 4321)
    h.headers = {"Content-Type": f"multipart/form-data; boundary={GRENSE}",
                 "Content-Length": str(len(kropp))}
    h.rfile = io.BytesIO(kropp)
    # R161 setter en frist rundt selve kroppslesingen, og gjør det på
    # socketen. Uten en stand-in her faller ruta på AttributeError før
    # den rekker fram til det testen handler om.
    h.connection = types.SimpleNamespace(gettimeout=lambda: None,
                                         settimeout=lambda s: None)
    # Auth og ratebegrensning er ikke det denne testen handler om — og
    # de leser miljøet, som gjør grønt maskinavhengig (R174).
    h._autorisert = lambda: True
    h._rate_ok = lambda: True
    h._klient_id = "test"
    fanget = {}
    h.send_response = lambda k: fanget.__setitem__("kode", k)
    h.send_header = lambda n, v: None
    h.end_headers = lambda: None
    h.wfile = types.SimpleNamespace(
        write=lambda b: fanget.__setitem__(
            "kropp", __import__("json").loads(b)))
    h._cors_origin = lambda: None
    return h, fanget


@pytest.fixture
def stubbet_modell(monkeypatch):
    """Bytter ut modellkallet og HUSKER argumentene det fikk."""
    sett = {}

    def _stubb(raa_tekst, sporsmal, ocr_brukt, handskrift, strekkoder,
               strekkoder_lest=True):
        sett["strekkoder_lest"] = strekkoder_lest
        sett["sporsmal"] = sporsmal
        return {"tom": False, "advarsler": [], "svar": "stubbsvar",
                "tall_verifisert": True, "uverifiserte_tall": [],
                "tallvakt_forsok": 1, "tolket_sporsmal": sporsmal,
                "svar_avkortet": False, "modell_brukt": True}

    monkeypatch.setattr(api, "svar_paa_sporsmal", _stubb)
    # Ruta har en port som gir 503 hvis Borealis ikke står «klar». Uten
    # dette avgjøres grønt av om modellen tilfeldigvis kjørte på DENNE
    # maskinen — nøyaktig den maskinavhengigheten R174 handlet om. Det
    # er ingen snarvei: modellkallet er alt byttet ut over.
    monkeypatch.setitem(api._borealis, "status", "klar")
    return sett


def _tekstlag_pdf() -> bytes:
    """PDF MED tekstlag: ingen OCR, ingen GPU, ingen ventetid."""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    side = doc.new_page()
    side.insert_text((72, 100), "Vedtak om sykepenger. Total Kr: 486,00")
    data = doc.tobytes()
    doc.close()
    return data


# ------------------------------------------------------------------ #
#  Selve regresjonen: veien skal svare, ikke smelle                    #
# ------------------------------------------------------------------ #

def test_pdf_med_sporsmal_gir_svar_ikke_500(stubbet_modell):
    """Nøyaktig kallet brukeren gjorde: PDF + «Hva er fnr»."""
    h, fanget = _handler(_kropp(b"vedtak.pdf", _tekstlag_pdf(),
                                sporsmal="Hva er fnr"))
    h.do_POST()
    assert fanget["kode"] == 200, fanget.get("kropp")
    assert fanget["kropp"]["modus"] == "dokumentsporsmal"
    assert fanget["kropp"]["svar"] == "stubbsvar"


def test_tekstfil_med_sporsmal_gir_svar_ikke_500(stubbet_modell):
    """Tekstgrenen (.txt/.docx) — egen vei, eget sett variabler."""
    h, fanget = _handler(_kropp(b"notat.txt", "Sum: 486 kroner".encode(),
                                sporsmal="Hva er summen"))
    h.do_POST()
    assert fanget["kode"] == 200, fanget.get("kropp")
    assert fanget["kropp"]["modus"] == "dokumentsporsmal"


# ------------------------------------------------------------------ #
#  …og flagget den krasjende linja skulle bære, skal være ÆRLIG (R159) #
# ------------------------------------------------------------------ #

def test_pdf_uten_strekkodebryter_melder_at_skanningen_kjorte(stubbet_modell):
    h, _ = _handler(_kropp(b"vedtak.pdf", _tekstlag_pdf(),
                           sporsmal="Hva er fnr"))
    h.do_POST()
    assert stubbet_modell["strekkoder_lest"] is True


def test_pdf_med_strekkoder_nei_melder_at_den_IKKE_kjorte(stubbet_modell):
    """Slås dekoderen av, er «ingen strekkoder funnet» en løgn."""
    h, _ = _handler(_kropp(b"vedtak.pdf", _tekstlag_pdf(),
                           sporsmal="Hva er fnr", strekkoder="nei"))
    h.do_POST()
    assert stubbet_modell["strekkoder_lest"] is False


def test_tekstfil_melder_at_skanningen_aldri_kjorte(stubbet_modell):
    """En .txt har ingen bilder. Dekoderen kalles aldri — og da skal
    svaret ikke påstå at vi lette."""
    h, _ = _handler(_kropp(b"notat.txt", b"Sum: 486 kroner",
                           sporsmal="Hva er summen"))
    h.do_POST()
    assert stubbet_modell["strekkoder_lest"] is False
