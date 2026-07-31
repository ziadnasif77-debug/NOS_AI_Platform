"""
/fyll_skjema fikk de samme tre motorene som /dokument: felter
(deterministisk), auto (hybrid) og modell (Borealis, standard). Vi driver
_fyll_skjema_flyt med en lett fake-handler (tekst-dokument, ingen OCR) og
mocker modellen — så motor-forgreningen prøves GPU-fritt.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import dokument_api


DOK = ("HADSEL TRYGDEKONTOR\n"
       "Telefon 76118610\n"
       "8450 STOKMARKNES\n"
       "Gjelder barnetrygd for Terje Karlsen.\n")


def _lag_handler():
    H = dokument_api.Handler

    class Fake:
        _fyll_skjema_flyt = H._fyll_skjema_flyt

        def __init__(self):
            self.svar = None

        def _svar(self, kode, data, hoder=None):
            self.svar = (kode, data)
            return (kode, data)

    return Fake()


def _fyll(mal, motor, innhold=DOK):
    f = _lag_handler()
    f._fyll_skjema_flyt("dok.txt", "tekst", innhold, None, mal,
                        skjema_motor=motor)
    return f.svar


@pytest.fixture
def borealis_klar(monkeypatch):
    monkeypatch.setitem(dokument_api._borealis, "status", "klar")


# ------------------------------------------------------------------ #
#  felter-motoren: deterministisk, krever ALDRI Borealis              #
# ------------------------------------------------------------------ #

def test_felter_motor_uten_borealis(monkeypatch):
    monkeypatch.setitem(dokument_api._borealis, "status", "nede")
    kode, data = _fyll({"tlf": "{telefon}", "stonad": "{ytelse}"}, "felter")
    assert kode == 200 and data["motor"] == "felter"
    assert data["skjema"] == {"tlf": "76118610", "stonad": "barnetrygd"}
    assert data["avvik"] == []


def test_felter_motor_rapporterer_ukjente():
    kode, data = _fyll({"navn": "{navn}"}, "felter")
    assert kode == 200
    assert data["skjema"]["navn"] is None
    assert "navn" in data["ukjente_felter"]


# ------------------------------------------------------------------ #
#  modell-motoren: krever Borealis                                    #
# ------------------------------------------------------------------ #

def test_modell_motor_uten_borealis_gir_503(monkeypatch):
    monkeypatch.setitem(dokument_api._borealis, "status", "nede")
    kode, data = _fyll({"a": "{telefon}"}, "modell")
    assert kode == 503 and "Borealis" in data["feil"]


def test_modell_motor_med_mocket_borealis(borealis_klar, monkeypatch):
    def _stub(dok, mal):
        return {"ok": True, "skjema": {"a": "76118610"}, "avvik": []}
    monkeypatch.setattr(dokument_api, "fyll_skjema_kjerne", _stub)

    kode, data = _fyll({"a": "{telefon}"}, "modell")
    assert kode == 200 and data["motor"] == "modell"
    assert data["skjema"] == {"a": "76118610"}


# ------------------------------------------------------------------ #
#  auto-motoren: deterministisk + modell for hull, degraderer         #
# ------------------------------------------------------------------ #

def test_auto_motor_uten_borealis_degraderer(monkeypatch):
    monkeypatch.setitem(dokument_api._borealis, "status", "nede")
    kode, data = _fyll({"tlf": "{telefon}", "navn": "{navn}"}, "auto")
    assert kode == 200 and data["motor"] == "auto"
    assert data["skjema"]["tlf"] == "76118610"
    assert data["skjema"]["navn"] is None      # ikke funnet, ikke gjettet
    assert data["modell_brukt"] is False


def test_auto_motor_bruker_modell_for_hull(borealis_klar, monkeypatch):
    def _stub(dok, mal):
        return {"ok": True, "skjema": {k: "Terje Karlsen" for k in mal},
                "avvik": []}
    monkeypatch.setattr(dokument_api, "fyll_skjema_kjerne", _stub)

    kode, data = _fyll({"tlf": "{telefon}", "navn": "{navn}"}, "auto")
    assert kode == 200
    assert data["skjema"]["tlf"] == "76118610"
    assert data["skjema"]["navn"] == "Terje Karlsen"
    assert data["kilde_per_felt"]["telefon"] == "deterministisk"
    assert data["kilde_per_felt"]["navn"] == "modell"
    assert data["modell_brukt"] is True
