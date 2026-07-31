"""
Tester for NAV-API-konvensjonene som ble lagt til etter sammenligning
med et ekte NAV-endepunkt (PATCH /api/v1/oppgaver):

  1) stiene svarer også med /api/v1-prefiks (samme endepunkt)
  2) X-Correlation-ID ekkoes / genereres, og saneres mot hode-injeksjon
  3) feilsvar har {ok:false, feil, uuid} der uuid = korrelasjons-ID-en

Testene lager en Handler uten socket og kaller metodene direkte, så de
verken binder port eller laster modeller.
"""
import sys
import types

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import dokument_api as api


def _handler(headers=None, path="/hjelp"):
    """En Handler-instans som ikke er koblet til en socket. Vi omgår
    __init__ (som ville lest fra en strøm) og setter bare det metodene
    trenger."""
    h = api.Handler.__new__(api.Handler)
    h.headers = headers or {}
    h.path = path
    h.command = "GET"
    h.client_address = ("127.0.0.1", 12345)
    return h


# ---------- 1) /api/v1-prefiks ----------
def test_api_v1_prefiks_gir_samme_sti():
    for full, forventet in [
        ("/api/v1/spor", "/spor"),
        ("/api/v1/dokument?x=1", "/dokument"),
        ("/api/spor", "/spor"),
        ("/spor", "/spor"),            # uten prefiks fortsatt gyldig
        ("/api/v1", "/hjelp"),         # bar prefiks → hjelp
        ("/api/v1/jobb/abc/avbryt", "/jobb/abc/avbryt"),
    ]:
        h = _handler(path=full)
        assert h._sti() == forventet, full


def test_vanlig_sti_uten_prefiks_er_urort():
    # de gamle stiene skal ikke endres av prefiks-strippingen
    for sti in ("/analyser", "/uttrekk", "/fyll_skjema"):
        assert _handler(path=sti)._sti() == sti
    # etterfølgende skråstrek fjernes fortsatt
    assert _handler(path="/spor/")._sti() == "/spor"


# ---------- 2) X-Correlation-ID ----------
def test_klientens_korrelasjonsid_beholdes():
    h = _handler(headers={"X-Correlation-ID": "min-sak-123"})
    assert h._korrelasjonsid() == "min-sak-123"


def test_korrelasjonsid_genereres_naar_den_mangler():
    h = _handler()
    kid = h._korrelasjonsid()
    assert kid and len(kid) >= 16
    # bufres: samme verdi hver gang innen samme forespørsel
    assert h._korrelasjonsid() == kid


def test_korrelasjonsid_saneres_mot_hodeinjeksjon():
    """CR/LF og kolon MÅ bort — ellers kan en klientstyrt verdi splitte
    svar-hoder eller forfalske en loggrad."""
    h = _handler(headers={"X-Correlation-ID": "ond\r\nEvil: 1"})
    kid = h._korrelasjonsid()
    for farlig in ("\r", "\n", ":", " "):
        assert farlig not in kid
    assert kid.startswith("ondEvil1")


def test_korrelasjonsid_kappes_til_64():
    h = _handler(headers={"X-Correlation-ID": "a" * 500})
    assert len(h._korrelasjonsid()) == 64


def test_tom_korrelasjonsid_gir_generert():
    h = _handler(headers={"X-Correlation-ID": "   "})
    assert len(h._korrelasjonsid()) >= 16      # falt tilbake til generert


# ---------- 3) uuid i feilkropp ----------
def _fanget_svar(h):
    """Bytter ut nettverksdelen av _svar med en oppsamler, så vi ser
    nøyaktig hva som ville blitt sendt."""
    fanget = {}

    def falsk_send_response(kode):
        fanget["kode"] = kode

    def falsk_send_header(navn, verdi):
        fanget.setdefault("hoder", {})[navn] = verdi

    h.send_response = falsk_send_response
    h.send_header = falsk_send_header
    h.end_headers = lambda: None
    h.wfile = types.SimpleNamespace(write=lambda b: fanget.__setitem__("kropp", b))
    h._cors_origin = lambda: None
    return fanget


def test_feilsvar_faar_uuid_lik_korrelasjonsid():
    import json
    h = _handler(headers={"X-Correlation-ID": "sak-999"})
    fanget = _fanget_svar(h)
    h._svar(400, {"ok": False, "feil": "noe gikk galt"})
    kropp = json.loads(fanget["kropp"].decode("utf-8"))
    assert kropp["uuid"] == "sak-999"
    assert fanget["hoder"]["X-Correlation-ID"] == "sak-999"


def test_vellykket_svar_faar_ikke_uuid():
    import json
    h = _handler()
    fanget = _fanget_svar(h)
    h._svar(200, {"ok": True, "svar": "alt bra"})
    kropp = json.loads(fanget["kropp"].decode("utf-8"))
    assert "uuid" not in kropp
    # men korrelasjons-hodet skal likevel være der
    assert "X-Correlation-ID" in fanget["hoder"]


def test_korrelasjonshode_paa_alle_svar():
    h = _handler()
    fanget = _fanget_svar(h)
    h._svar(200, {"ok": True})
    assert fanget["hoder"]["X-Correlation-ID"]
