"""
Glue-laget for det nye operasjoner-kontraktet på POST /dokument:
_dokument_operasjoner (JSON-parsing, validering, 503-port,
svar-sammensetning). Vi driver metoden med en LETT fake-handler som fanger
_svar(kode, data) i stedet for å skrive til en socket — så vi slipper HTTP,
men prøver den EKTE handler-koden.

Dokumentet gis som ren tekst (slag="tekst"), så ingen OCR/analyse trengs.
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
    """Fake-handler som låner de EKTE metodene fra Handler, men bytter ut
    _svar med en fanger. Klassene slås opp gjennom modulen ved kalltid, så
    testen tåler importlib.reload i andre testmoduler."""
    H = dokument_api.Handler

    class Fake:
        MAKS_OPERASJONER = H.MAKS_OPERASJONER
        _les_dokument = H._les_dokument
        _dokument_operasjoner = H._dokument_operasjoner

        def __init__(self):
            self.svar = None

        def _svar(self, kode, data, hoder=None):
            self.svar = (kode, data)
            return (kode, data)

    return Fake()


def _kjor(operasjoner_raa, innhold=DOK):
    f = _lag_handler()
    f._dokument_operasjoner("dok.txt", "tekst", innhold, None, True,
                            operasjoner_raa)
    return f.svar


@pytest.fixture
def borealis_klar(monkeypatch):
    monkeypatch.setitem(dokument_api._borealis, "status", "klar")


# ------------------------------------------------------------------ #
#  Lykkelig sti                                                       #
# ------------------------------------------------------------------ #

def test_felteroperasjon_gir_resultater():
    kode, data = _kjor('[{"type":"felter"}]')
    assert kode == 200 and data["ok"] is True
    assert len(data["resultater"]) == 1
    r = data["resultater"][0]
    assert r["type"] == "felter" and r["ok"] is True
    assert r["data"]["felter"]["telefon"] == "76118610"


def test_skjema_felter_motor_flettes_deterministisk():
    mal = '{"tlf":"{telefon}","stonad":"{ytelse}"}'
    kode, data = _kjor(
        '[{"type":"skjema","motor":"felter","mal":' + mal + '}]')
    assert kode == 200
    r = data["resultater"][0]
    assert r["ok"] is True and r["motor"] == "felter"
    # ytelse hentes korrekt fra kanonisk liste — IKKE beløpet
    assert r["data"] == {"tlf": "76118610", "stonad": "barnetrygd"}


def test_flere_operasjoner_i_rekkefolge():
    kode, data = _kjor(
        '[{"type":"felter"},'
        ' {"type":"skjema","motor":"felter","mal":{"tlf":"{telefon}"}}]')
    assert kode == 200
    assert [r["type"] for r in data["resultater"]] == ["felter", "skjema"]


def test_godtar_innpakket_operasjoner_objekt():
    """Både {"operasjoner":[...]} og en ren [...] skal godtas."""
    kode, data = _kjor('{"operasjoner":[{"type":"felter"}]}')
    assert kode == 200 and data["resultater"][0]["type"] == "felter"


# ------------------------------------------------------------------ #
#  Validering → 400                                                   #
# ------------------------------------------------------------------ #

def test_ugyldig_json_gir_400():
    kode, data = _kjor("{ikke gyldig json")
    assert kode == 400 and "Ugyldig JSON" in data["feil"]


def test_tom_liste_gir_400():
    kode, data = _kjor("[]")
    assert kode == 400 and "ikke-tom liste" in data["feil"]


def test_ukjent_type_gir_400():
    kode, data = _kjor('[{"type":"tull"}]')
    assert kode == 400 and "ukjent operasjonstype" in data["feil"]


def test_skjema_uten_mal_gir_400():
    kode, data = _kjor('[{"type":"skjema","motor":"felter"}]')
    assert kode == 400 and "krever 'mal'" in data["feil"]


def test_for_mange_operasjoner_gir_400():
    mange = "[" + ",".join(['{"type":"felter"}'] * 25) + "]"
    kode, data = _kjor(mange)
    assert kode == 400 and "For mange operasjoner" in data["feil"]


def test_manglende_fil_gir_400():
    f = _lag_handler()
    f._dokument_operasjoner("dok.txt", "tekst", None, None, True,
                            '[{"type":"felter"}]')
    kode, data = f.svar
    assert kode == 400 and "Ingen fil" in data["feil"]


# ------------------------------------------------------------------ #
#  503-port: bare modelldeler mens Borealis er nede                   #
# ------------------------------------------------------------------ #

def test_bare_modelldeler_uten_borealis_gir_503(monkeypatch):
    monkeypatch.setitem(dokument_api._borealis, "status", "nede")
    kode, data = _kjor('[{"type":"svar","sporsmal":"Hva er beløpet?"}]')
    assert kode == 503 and "Borealis" in data["feil"]


def test_rask_del_med_gir_200_selv_om_borealis_nede(monkeypatch):
    """Er minst én rask del med, svarer vi 200 — modelldelen blir et
    ok:False-resultat, ikke en 503 for hele kallet."""
    monkeypatch.setitem(dokument_api._borealis, "status", "nede")
    kode, data = _kjor(
        '[{"type":"felter"},{"type":"svar","sporsmal":"Hva?"}]')
    assert kode == 200
    typer = {r["type"]: r for r in data["resultater"]}
    assert typer["felter"]["ok"] is True
    assert typer["svar"]["ok"] is False and "Borealis" in typer["svar"]["feil"]
