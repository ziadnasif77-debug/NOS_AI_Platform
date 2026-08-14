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


# ------------------------------------------------------------------ #
#  Mellombåndet (R187): andre-sjekk før et menneske bryes             #
# ------------------------------------------------------------------ #
#
# Konfidens i [GJENNOMGANG_NEDRE, LS_KONFIDENS_TERSKEL) holdes tilbake
# BARE når typeforventningene beviser at alt dokumenttypen krever, ble
# funnet. Tomt resultat og håndskrift båndes aldri, og beslutningen
# logges så båndet kan måles (R149).

KOMPLETT_FAKTURA = ("Faktura\n"
                    "Org.nr. 923 609 016\n"
                    "Fakturadato: 12.06.2026\n"
                    "Totalt: 1 234,00 kr\n")


@pytest.fixture
def api_band(monkeypatch):
    """Auto-gjennomgang PÅ med aktivt mellombånd [0.70, 0.85)."""
    monkeypatch.setenv("LABEL_STUDIO_URL", "http://localhost:8080")
    monkeypatch.setenv("LABEL_STUDIO_API_KEY", "test-nokkel")
    monkeypatch.setenv("GJENNOMGANG_NEDRE", "0.70")
    import dokument_api
    importlib.reload(dokument_api)
    return dokument_api


def _uten_traad(api, monkeypatch):
    monkeypatch.setattr(api.threading, "Thread",
                        lambda *a, **k: type("T", (), {"start": lambda s: None})())


def test_mellomband_holder_tilbake_naar_alt_forventet_er_funnet(
        api_band, monkeypatch):
    _uten_traad(api_band, monkeypatch)
    ocr = {"konfidens": 0.78, "tekst": KOMPLETT_FAKTURA, "handskrift": []}
    res = api_band._kanskje_send_til_gjennomgang("f.pdf", b"%PDF", ocr, {})
    assert res is None
    assert ocr["_gjennomgang_vurdering"] == "mellomband_holdt_tilbake:faktura"


def test_mellomband_sender_naar_noe_mangler(api_band, monkeypatch):
    """Vedtak uten fnr og dato: andre-sjekken kan ikke bevise noe →
    mennesket får dokumentet, som før."""
    _uten_traad(api_band, monkeypatch)
    ocr = {"konfidens": 0.78, "handskrift": [],
           "tekst": "Vedtak om barnetrygd\nGjelder barnetrygd for parten.\n"}
    res = api_band._kanskje_send_til_gjennomgang("v.pdf", b"%PDF", ocr, {})
    assert res["grunn"] == "lav_ocr_konfidens"
    assert "_gjennomgang_vurdering" not in ocr


def test_under_nedre_sendes_uansett(api_band, monkeypatch):
    """Under båndet er lesingen for dårlig til at en regelsjekk kan
    frikjenne den — komplett eller ei."""
    _uten_traad(api_band, monkeypatch)
    ocr = {"konfidens": 0.50, "tekst": KOMPLETT_FAKTURA, "handskrift": []}
    res = api_band._kanskje_send_til_gjennomgang("f.pdf", b"%PDF", ocr, {})
    assert res["grunn"] == "lav_ocr_konfidens"


def test_handskrift_bandes_aldri(api_band, monkeypatch):
    """Håndskrift er et kvalitativt signal som mater treningsløkken —
    mellombåndet skal ikke sulte den."""
    _uten_traad(api_band, monkeypatch)
    ocr = {"konfidens": 0.78, "tekst": KOMPLETT_FAKTURA,
           "handskrift": ["signatur"]}
    res = api_band._kanskje_send_til_gjennomgang("f.pdf", b"%PDF", ocr, {})
    assert res["grunn"] == "lav_ocr_konfidens"


def test_standard_er_tomt_band(api_paa, monkeypatch):
    """Uten GJENNOMGANG_NEDRE er båndet tomt: dagens oppførsel, nøyaktig
    (R149: en umålt terskel skal ikke få en umålt nabo)."""
    _uten_traad(api_paa, monkeypatch)
    assert api_paa.GJENNOMGANG_NEDRE == api_paa.LS_KONFIDENS_TERSKEL
    ocr = {"konfidens": 0.80, "tekst": KOMPLETT_FAKTURA, "handskrift": []}
    res = api_paa._kanskje_send_til_gjennomgang("f.pdf", b"%PDF", ocr, {})
    assert res["grunn"] == "lav_ocr_konfidens"


def test_snudd_band_klemmes_til_tomt(monkeypatch):
    """GJENNOMGANG_NEDRE over terskelen er en feilkonfigurasjon — den
    skal gi dagens oppførsel, ikke et bånd som slår ut over terskelen."""
    monkeypatch.setenv("LABEL_STUDIO_URL", "http://localhost:8080")
    monkeypatch.setenv("LABEL_STUDIO_API_KEY", "test-nokkel")
    monkeypatch.setenv("GJENNOMGANG_NEDRE", "0.99")
    import dokument_api
    importlib.reload(dokument_api)
    assert dokument_api.GJENNOMGANG_NEDRE == dokument_api.LS_KONFIDENS_TERSKEL


def test_tilbakeholdet_naar_tilgangsloggen(api_band):
    """Beslutningen skal kunne MÅLES: uten sending logges mellombåndets
    vurdering i samme felt som gjennomgangsgrunnen ellers står i."""
    class Dummy:
        pass
    handler = Dummy()
    api_band.Handler._noter_kalibrering(handler, {
        "ocr_konfidens": 0.78, "sendt_til_gjennomgang": None,
        "_gjennomgang_vurdering": "mellomband_holdt_tilbake:faktura"})
    assert handler._gjennomgang_grunn == "mellomband_holdt_tilbake:faktura"
    assert handler._ocr_konfidens == 0.78
    # Sending vinner over vurderingen — de kan aldri stå samtidig
    api_band.Handler._noter_kalibrering(handler, {
        "ocr_konfidens": 0.50,
        "sendt_til_gjennomgang": {"grunn": "lav_ocr_konfidens"}})
    assert handler._gjennomgang_grunn == "lav_ocr_konfidens"


def test_avkortet_handskrift_bandes_aldri(api_band, monkeypatch):
    """`handskrift_avkortet` betyr at kandidater FANTES men aldri ble
    lest — et slikt dokument skal til mennesket uansett hvor komplett
    den trykte delen ser ut (funn fra gjennomgangen av R187)."""
    _uten_traad(api_band, monkeypatch)
    ocr = {"konfidens": 0.78, "tekst": KOMPLETT_FAKTURA, "handskrift": [],
           "handskrift_avkortet": True}
    res = api_band._kanskje_send_til_gjennomgang("f.pdf", b"%PDF", ocr, {})
    assert res["grunn"] == "lav_ocr_konfidens"
    assert "_gjennomgang_vurdering" not in ocr


def test_bandet_proevetar_saa_fasiten_finnes(api_band, monkeypatch):
    """Uten en prøveandel inne i båndet får ingen tilbakeholdte
    dokumenter noensinne fasit — båndet ville gjenskapt blindsonen R149
    fjernet. Med andel 1.0 sendes bånddokumentet, merket som båndprøve."""
    _uten_traad(api_band, monkeypatch)
    monkeypatch.setattr(api_band, "KALIBRERING_ANDEL", 1.0)
    ocr = {"konfidens": 0.78, "tekst": KOMPLETT_FAKTURA, "handskrift": []}
    res = api_band._kanskje_send_til_gjennomgang("f.pdf", b"%PDF", ocr, {})
    assert res["grunn"] == "mellomband_kalibreringsproeve"
    assert "_gjennomgang_vurdering" not in ocr
