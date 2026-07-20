"""
Tester for auto-gjennomgang: leser serveren et dokument dårlig, sender
den det automatisk til Label Studio for menneskelig korreksjon (som
mater treningsløkken).

Testene rører aldri et ekte Label Studio — de sjekker BESLUTNINGEN
(sende eller ikke) og at funksjonen er trygt AV når Label Studio ikke er
konfigurert. Selve HTTP-sendingen skjer i en bakgrunnstråd og er
best-effort.
"""
import importlib
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest


@pytest.fixture
def api_av(monkeypatch):
    """dokument_api UTEN Label Studio konfigurert (standard)."""
    monkeypatch.delenv("LABEL_STUDIO_URL", raising=False)
    monkeypatch.delenv("LABEL_STUDIO_API_KEY", raising=False)
    import dokument_api
    importlib.reload(dokument_api)
    return dokument_api


@pytest.fixture
def api_paa(monkeypatch):
    """dokument_api MED Label Studio konfigurert (auto-gjennomgang på).
    Sendefunksjonen stubbes så ingen ekte HTTP skjer."""
    monkeypatch.setenv("LABEL_STUDIO_URL", "http://localhost:8080")
    monkeypatch.setenv("LABEL_STUDIO_API_KEY", "test-nokkel")
    import dokument_api
    importlib.reload(dokument_api)
    return dokument_api


def test_av_som_standard(api_av):
    """Uten Label Studio konfigurert skal auto-gjennomgang være AV, og
    ingenting sendes — «lagrer ingenting»-oppførselen bevares."""
    assert api_av.AUTO_GJENNOMGANG is False
    ocr = {"konfidens": 0.30, "tekst": "n" * 40, "handskrift": []}
    assert api_av._kanskje_send_til_gjennomgang("d.pdf", b"%PDF", ocr, {}) is None


def test_god_lesing_sendes_ikke(api_paa):
    """Høy konfidens og ingen håndskrift → ingen grunn til gjennomgang."""
    ocr = {"konfidens": 0.95, "tekst": "god tekst " * 10, "handskrift": []}
    assert api_paa._kanskje_send_til_gjennomgang("d.pdf", b"%PDF", ocr, {}) is None


def test_lav_konfidens_sendes(api_paa, monkeypatch):
    """Lav OCR-konfidens → sendes til gjennomgang med riktig grunn."""
    sendt = {}
    monkeypatch.setattr(api_paa.threading, "Thread",
                        lambda *a, **k: type("T", (), {"start": lambda s: sendt.setdefault("ja", True)})())
    ocr = {"konfidens": 0.50, "tekst": "usikker " * 10, "handskrift": []}
    res = api_paa._kanskje_send_til_gjennomgang("d.pdf", b"%PDF", ocr, {})
    assert res["grunn"] == "lav_ocr_konfidens"
    assert res["konfidens"] == 0.50


def test_handskrift_sendes(api_paa, monkeypatch):
    """Håndskrift er usikker (norhand) → sendes selv med høy konfidens."""
    monkeypatch.setattr(api_paa.threading, "Thread",
                        lambda *a, **k: type("T", (), {"start": lambda s: None})())
    ocr = {"konfidens": 0.95, "tekst": "tekst " * 10, "handskrift": ["signatur"]}
    res = api_paa._kanskje_send_til_gjennomgang("d.pdf", b"%PDF", ocr, {})
    assert res["grunn"] == "handskrift"


def test_tomt_resultat_sendes(api_paa, monkeypatch):
    """OCR fant nesten ingen tekst → dårlig lest → til gjennomgang."""
    monkeypatch.setattr(api_paa.threading, "Thread",
                        lambda *a, **k: type("T", (), {"start": lambda s: None})())
    ocr = {"konfidens": 1.0, "tekst": "x", "handskrift": []}
    res = api_paa._kanskje_send_til_gjennomgang("d.pdf", b"%PDF", ocr, {})
    assert res["grunn"] == "tomt_resultat"


def test_uten_ocr_sendes_aldri(api_paa):
    """Ble OCR aldri brukt (tekst-PDF), er det ingenting å korrigere."""
    assert api_paa._kanskje_send_til_gjennomgang("d.pdf", b"%PDF", None, {}) is None
