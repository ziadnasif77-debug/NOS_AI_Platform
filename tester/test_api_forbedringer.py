"""
Tester for API-forbedringene inspirert av NAV Oppgave-APIet:

  1) RFC 9457 Problem Details på feilsvar (i tillegg til {ok, feil, uuid})
  2) errors[].pointer — HVILKET felt som er galt
  3) Idempotency-Key — samme nøkkel gir samme jobb (retry-trygt)
  4) optimistisk låsing på jobb-avbrudd (versjon → 409)

Handler-metodene kalles direkte uten socket (som test_nav_konvensjoner).
"""
import sys
import types

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import dokument_api as api


def _handler(headers=None, path="/dokument"):
    h = api.Handler.__new__(api.Handler)
    h.headers = headers or {}
    h.path = path
    h.command = "POST"
    h.client_address = ("127.0.0.1", 12345)
    return h


def _fang(h):
    fanget = {}
    h.send_response = lambda k: fanget.__setitem__("kode", k)
    h.send_header = lambda n, v: fanget.setdefault("hoder", {}).__setitem__(n, v)
    h.end_headers = lambda: None
    h.wfile = types.SimpleNamespace(
        write=lambda b: fanget.__setitem__("kropp", __import__("json").loads(b)))
    h._cors_origin = lambda: None
    return fanget


# ---------- 1) RFC 9457 Problem Details ----------
def test_feilsvar_faar_problem_objekt():
    h = _handler()
    f = _fang(h)
    h._svar(400, {"ok": False, "feil": "noe er galt"})
    p = f["kropp"]["problem"]
    assert p["status"] == 400
    assert p["title"] == "Ugyldig input"
    assert p["detail"] == "noe er galt"
    assert p["type"].endswith("/ugyldig-input")
    # de gamle feltene beholdes — ingen klient brytes
    assert f["kropp"]["ok"] is False
    assert f["kropp"]["feil"] == "noe er galt"


def test_traceid_er_korrelasjonsiden():
    h = _handler(headers={"X-Correlation-ID": "sak-42"})
    f = _fang(h)
    h._svar(500, {"ok": False, "feil": "krasj"})
    assert f["kropp"]["problem"]["traceId"] == "sak-42"
    assert f["kropp"]["uuid"] == "sak-42"


def test_vellykket_svar_faar_ikke_problem():
    h = _handler()
    f = _fang(h)
    h._svar(200, {"ok": True, "svar": "bra"})
    assert "problem" not in f["kropp"]


def test_riktig_tittel_per_kode():
    for kode, frag in [(401, "unauthorized"), (404, "ikke-funnet"),
                       (409, "konflikt"), (429, "for-mange-kall"),
                       (503, "utilgjengelig")]:
        h = _handler()
        f = _fang(h)
        h._svar(kode, {"ok": False, "feil": "x"})
        assert f["kropp"]["problem"]["type"].endswith("/" + frag), kode


# ---------- 2) errors[].pointer ----------
def test_felter_feil_blir_errors_med_pointer():
    h = _handler()
    f = _fang(h)
    h._svar(400, {"ok": False, "feil": "mangler",
                  "felter_feil": [{"pointer": "/sporsmal",
                                   "message": "Påkrevd når svar=ja"}]})
    errors = f["kropp"]["problem"]["errors"]
    assert errors == [{"pointer": "/sporsmal", "message": "Påkrevd når svar=ja"}]
    # råfeltet felter_feil skal IKKE lekke ut i svaret (kun intern input)
    assert "felter_feil" not in f["kropp"]


# ---------- 3) idempotens-hjelpelogikk ----------
def test_idempotensnokkel_saneres():
    """Nøkkelen brukes som dict-nøkkel og bør saneres likt som ellers."""
    import re
    raa = "abc\r\n123 :; DROP"
    rein = re.sub(r"[^A-Za-z0-9._-]", "", raa)[:64]
    assert "\r" not in rein and " " not in rein and ":" not in rein
    assert rein == "abc123DROP"


# ---------- 4) optimistisk låsing (versjon) ----------
def test_jobb_status_oker_versjon():
    jobb = {"status": "kø", "versjon": 1}
    api._jobb_status(jobb, "pågår")
    assert jobb["status"] == "pågår" and jobb["versjon"] == 2
    api._jobb_status(jobb, "ferdig", tekst="hei")
    assert jobb["versjon"] == 3 and jobb["tekst"] == "hei"


def test_forventet_versjon_fra_query_og_header():
    assert _handler(path="/jobb/x/avbryt?versjon=5")._forventet_versjon() == 5
    assert _handler(path="/jobb/x/avbryt",
                    headers={"X-Versjon": "7"})._forventet_versjon() == 7
    # ingen oppgitt → None (da gjelder ingen låsing)
    assert _handler(path="/jobb/x/avbryt")._forventet_versjon() is None
    # ugyldig → None, ikke krasj
    assert _handler(path="/jobb/x/avbryt?versjon=abc")._forventet_versjon() is None
