"""
Tester for rate-limiting-kjernen (_rate_tillatt). Tester tellelogikken
per klient per minutt uten en HTTP-handler.
"""
import importlib
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest


def _last(monkeypatch, grense):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", str(grense))
    import dokument_api
    importlib.reload(dokument_api)
    return dokument_api


def test_av_ved_null(monkeypatch):
    """0 = av: aldri begrenset, uansett antall."""
    d = _last(monkeypatch, 0)
    assert all(d._rate_tillatt("1.2.3.4") for _ in range(500))


def test_grense_haandheves(monkeypatch):
    """Nøyaktig N tillatt, N+1 avvist innen samme minutt."""
    d = _last(monkeypatch, 5)
    ip = "9.9.9.9"
    assert all(d._rate_tillatt(ip) for _ in range(5))
    assert d._rate_tillatt(ip) is False
    assert d._rate_tillatt(ip) is False


def test_per_klient_isolert(monkeypatch):
    """Én klients bruk påvirker ikke en annens bøtte."""
    d = _last(monkeypatch, 3)
    for _ in range(3):
        d._rate_tillatt("klient-a")
    assert d._rate_tillatt("klient-a") is False   # a oppbrukt
    assert d._rate_tillatt("klient-b") is True     # b upåvirket
