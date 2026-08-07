"""
GET /innsyn/<id> må kreve API-nøkkel — den bærer hele dokumentet.

Funnet i en revisjon: lese-siden av /innsyn var den ENESTE dataveien
uten nøkkelsjekk. Målt mot kjørende server FØR fiksen: 246 KB JSON med
full utlest tekst OG base64-kodede sidebilder, uten en eneste header.

Id-en er 48 bits og deles bare med den som opprettet økta — men den
havner i tilgangslogg, proxy og nettleserhistorikk, og «vanskelig å
gjette» er ikke en tilgangskontroll.

Vakten testes uten socket, som resten av handler-testene.
"""
import sys
import types

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import dokument_api as api


def _handler(nokkel_header=None, sti="/innsyn/abc123"):
    h = api.Handler.__new__(api.Handler)
    h.headers = {"X-API-Key": nokkel_header} if nokkel_header else {}
    h.path = sti
    h.command = "GET"
    h.client_address = ("127.0.0.1", 4321)
    fanget = {}
    h.send_response = lambda k: fanget.__setitem__("kode", k)
    h.send_header = lambda n, v: None
    h.end_headers = lambda: None
    h.wfile = types.SimpleNamespace(
        write=lambda b: fanget.__setitem__(
            "kropp", __import__("json").loads(b)))
    h._cors_origin = lambda: None
    h._rate_ok = lambda: True
    return h, fanget


@pytest.fixture
def med_nokkel(monkeypatch):
    monkeypatch.setattr(api, "API_NOKKEL", "hemmelig-testnokkel")
    return "hemmelig-testnokkel"


def test_innsyn_uten_nokkel_gir_401(med_nokkel, monkeypatch):
    """Regresjonen: dette ga 200 med hele dokumentet."""
    monkeypatch.setitem(api._innsyn_okter, "abc123", {
        "status": "ferdig", "hendelser": [],
        "resultat": {"tekst": "HEMMELIG DOKUMENTINNHOLD"}, "feil": None})
    h, fanget = _handler()
    h._do_get_intern()
    assert fanget["kode"] == 401
    assert "HEMMELIG" not in str(fanget["kropp"])


def test_innsyn_med_riktig_nokkel_gir_data(med_nokkel, monkeypatch):
    monkeypatch.setitem(api._innsyn_okter, "abc123", {
        "status": "ferdig", "hendelser": [],
        "resultat": {"tekst": "dokumentinnhold"}, "feil": None,
        # Oekta maa eies av klienten som ber om den. Uten «eier» er den
        # utilgjengelig for ALLE — se test_okt_uten_eier_er_stengt.
        "eier": api.ELDRE})
    h, fanget = _handler(nokkel_header=med_nokkel)
    h._do_get_intern()
    assert fanget["kode"] == 200
    assert fanget["kropp"]["resultat"]["tekst"] == "dokumentinnhold"


def test_innsyn_med_feil_nokkel_gir_401(med_nokkel, monkeypatch):
    monkeypatch.setitem(api._innsyn_okter, "abc123", {
        "status": "ferdig", "hendelser": [], "resultat": {}, "feil": None})
    h, fanget = _handler(nokkel_header="feil-nokkel")
    h._do_get_intern()
    assert fanget["kode"] == 401


def test_ukjent_id_lekker_ikke_at_den_finnes(med_nokkel):
    """Nøkkelsjekken skal komme FØR oppslaget, ellers kan en uautentisert
    klient prøve seg fram og se forskjell på 404 og 200."""
    h, fanget = _handler(sti="/innsyn/finnesikke")
    h._do_get_intern()
    assert fanget["kode"] == 401        # ikke 404


def test_alle_get_dataveier_krever_nokkel():
    """Vakt mot at en ny GET-datavei glemmer nøkkelsjekken. /hjelp,
    /openapi.json og /dokumentasjon er bevisst åpne (metadata)."""
    import inspect
    kilde = inspect.getsource(api.Handler._do_get_intern)
    for vei in ('sti.startswith("/innsyn/")', 'sti.startswith("/jobb/")'):
        assert vei in kilde, f"fant ikke {vei} — er ruten flyttet?"
    # begge dataveiene må ha en autorisert-sjekk i grenen sin
    etter_innsyn = kilde.split('sti.startswith("/innsyn/")')[1][:600]
    assert "_autorisert()" in etter_innsyn
    etter_jobb = kilde.split('sti.startswith("/jobb/")')[1][:600]
    assert "_autorisert()" in etter_jobb


def test_innsyn_tar_kapasitetsplass():
    """Bakgrunnstråden må holde en kapasitetsplass — ellers kan N kall
    starte N samtidige OCR-tråder om det ene skjermkortet."""
    import inspect
    kilde = inspect.getsource(api.Handler._innsyn)
    assert "_kapasitet_port.ta(" in kilde
    assert "_kapasitet_port.slipp()" in kilde


# ------------------------------------------------------------------ #
#  Eierskap: en GYLDIG nøkkel er ikke det samme som SAMME nøkkel       #
# ------------------------------------------------------------------ #

def test_annen_klient_faar_ikke_lese_okta(monkeypatch):
    """Hullet: sjekken spurte om nøkkelen var GYLDIG, ikke om den var
    den SAMME. Med navngitte nøkler kunne enhver autentisert klient lese
    enhver annens innsyn_id — og økta bærer hele dokumentteksten og
    sidebilder i base64.

    404, ikke 403: en fremmed skal ikke få vite at id-en finnes."""
    monkeypatch.setattr(api, "API_NOKKEL", "")
    monkeypatch.setattr(api, "API_NOKLER",
                        {"robot-a": "noekkel-a-lang-nok-for-vakten-1234",
                         "robot-b": "noekkel-b-lang-nok-for-vakten-1234"})
    monkeypatch.setitem(api._innsyn_okter, "abc123", {
        "status": "ferdig", "hendelser": [],
        "resultat": {"tekst": "HEMMELIG DOKUMENTINNHOLD"},
        "feil": None, "eier": "robot-a"})

    h, fanget = _handler(nokkel_header="noekkel-b-lang-nok-for-vakten-1234")
    h._do_get_intern()
    assert fanget["kode"] == 404, "en annen klient skal ikke få lese økta"
    assert "HEMMELIG" not in str(fanget["kropp"])


def test_eieren_selv_faar_lese(monkeypatch):
    """Speilet — uten det ville en stengt dør vært «riktig» for alle."""
    monkeypatch.setattr(api, "API_NOKKEL", "")
    monkeypatch.setattr(api, "API_NOKLER",
                        {"robot-a": "noekkel-a-lang-nok-for-vakten-1234"})
    monkeypatch.setitem(api._innsyn_okter, "abc123", {
        "status": "ferdig", "hendelser": [],
        "resultat": {"tekst": "mitt eget dokument"},
        "feil": None, "eier": "robot-a"})

    h, fanget = _handler(nokkel_header="noekkel-a-lang-nok-for-vakten-1234")
    h._do_get_intern()
    assert fanget["kode"] == 200
    assert fanget["kropp"]["resultat"]["tekst"] == "mitt eget dokument"


def test_okt_uten_eier_er_stengt(med_nokkel, monkeypatch):
    """En økt uten registrert eier er utilgjengelig for alle.

    Øktene lever bare i minnet og dør med prosessen, så det finnes ingen
    «gamle» økter å ta hensyn til. Da er streng dør riktig: å slippe
    gjennom en eierløs økt ville gjenåpnet hullet for enhver som klarte
    å legge inn en."""
    monkeypatch.setitem(api._innsyn_okter, "abc123", {
        "status": "ferdig", "hendelser": [],
        "resultat": {"tekst": "HEMMELIG"}, "feil": None})
    h, fanget = _handler(nokkel_header=med_nokkel)
    h._do_get_intern()
    assert fanget["kode"] == 404


def test_ok_folger_operasjonen_ikke_oppslaget(med_nokkel, monkeypatch):
    """`ok` sto True selv når `status: "feil"`. En robot som ruter på
    `ok` — slik hver annen rute i dette API-et inviterer til — leste en
    mislykket dokumentlesing som en suksess."""
    monkeypatch.setitem(api._innsyn_okter, "abc123", {
        "status": "feil", "hendelser": [], "resultat": None,
        "feil": "Lesingen feilet", "eier": api.ELDRE})
    h, fanget = _handler(nokkel_header=med_nokkel)
    h._do_get_intern()
    assert fanget["kode"] == 200, "oppslaget lyktes — det er ikke 404"
    assert fanget["kropp"]["ok"] is False, "men lesingen gjorde ikke"
    assert fanget["kropp"]["feil"]


# ------------------------------------------------------------------ #
#  Levetid: økta bærer dokumentteksten og skal ikke ligge for evig     #
# ------------------------------------------------------------------ #

def test_utlopte_okter_ryddes(monkeypatch):
    """Den eneste oppryddingen var «behold de 6 nyeste», og den kjørte
    BARE når noen opprettet en ny økt. Sluttet opplastingen, ble seks
    dokumenter liggende i minnet resten av prosessens levetid. `start`
    ble registrert, men aldri lest."""
    import time as _t
    monkeypatch.setattr(api, "_innsyn_okter", {})
    monkeypatch.setattr(api, "INNSYN_LEVETID_S", 60)
    api._innsyn_okter["gammel"] = {"start": _t.time() - 3600,
                                   "status": "ferdig", "hendelser": []}
    api._innsyn_okter["fersk"] = {"start": _t.time(),
                                  "status": "ferdig", "hendelser": []}
    api._rydd_innsyn()
    assert "gammel" not in api._innsyn_okter
    assert "fersk" in api._innsyn_okter


def test_antallsgrensen_gjelder_fortsatt(monkeypatch):
    """Tid FØRST, antall etterpå — men begge må virke."""
    import time as _t
    monkeypatch.setattr(api, "_innsyn_okter", {})
    monkeypatch.setattr(api, "INNSYN_LEVETID_S", 9999)
    monkeypatch.setattr(api, "INNSYN_MAKS_OKTER", 3)
    for i in range(6):
        api._innsyn_okter[f"okt{i}"] = {"start": _t.time(),
                                        "status": "ferdig", "hendelser": []}
    api._rydd_innsyn()
    assert len(api._innsyn_okter) == 3
    assert "okt5" in api._innsyn_okter, "de NYESTE skal beholdes"
