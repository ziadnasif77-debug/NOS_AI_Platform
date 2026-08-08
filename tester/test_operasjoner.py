"""
Operasjonsmotoren: ETT dokument lest én gang (DokumentKontekst), mange
operasjoner kjørt mot samme kontekst. Disse testene prøver KJERNEN uten
HTTP-laget: dov caching, hver operasjons resultat, uavhengig
feilhåndtering, og fabrikkvalideringen (bygg_operasjon).

Modellen (Borealis) mockes, så alt er raskt og GPU-fritt.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import dokument_api
from dokument_api import (DokumentKontekst, FelterOperasjon, KorrigerOperasjon,
                          Operasjonsmotor, SkjemaOperasjon, StrukturOperasjon,
                          SvarOperasjon, TekstOperasjon, bygg_operasjon)


DOK = ("HADSEL TRYGDEKONTOR\n"
       "Telefon 76118610\n"
       "8450 STOKMARKNES\n"
       "Gjelder barnetrygd for Terje Karlsen.\n"
       "Totalt 6380.00 NOK\n")


@pytest.fixture
def ktx():
    return DokumentKontekst(DOK, ocr_brukt=True)


@pytest.fixture
def borealis_klar(monkeypatch):
    monkeypatch.setitem(dokument_api._borealis, "status", "klar")


# ------------------------------------------------------------------ #
#  DokumentKontekst: les-en-gang, regn-en-gang                        #
# ------------------------------------------------------------------ #

def test_felter_beregnes_dovent_og_caches(ktx, monkeypatch):
    """felter skal regnes FØRSTE gang og gjenbrukes — ikke to ganger."""
    kall = {"n": 0}
    ekte = dokument_api.utvid_entiteter

    def _teller(tekst, ent):
        kall["n"] += 1
        return ekte(tekst, ent)

    monkeypatch.setattr(dokument_api, "utvid_entiteter", _teller)
    _ = ktx.felter
    _ = ktx.felter               # andre gang: fra cache
    assert kall["n"] == 1


def test_felteroperasjon_finner_verdiene(ktx):
    res = FelterOperasjon().utfor(ktx)
    assert res["ok"] is True and res["type"] == "felter"
    assert res["data"]["felter"]["telefon"] == "76118610"
    assert "datoer" in res["data"] and "dokumentdato" in res["data"]


def test_tekstoperasjon_gir_teksten(ktx):
    res = TekstOperasjon().utfor(ktx)
    assert res["ok"] is True
    assert res["data"] == DOK


def test_er_tom_paa_blankt_dokument():
    assert DokumentKontekst("   ").er_tom() is True
    assert DokumentKontekst(DOK).er_tom() is False


# ------------------------------------------------------------------ #
#  SkjemaOperasjon: tre motorer                                       #
# ------------------------------------------------------------------ #

def test_skjema_motor_felter_er_deterministisk(ktx):
    """felter-motoren krever ALDRI Borealis — virker selv når den er nede."""
    op = SkjemaOperasjon({"tlf": "{telefon}", "sted": "{poststed}"}, "felter")
    res = op.utfor(ktx)
    assert res["ok"] is True and res["motor"] == "felter"
    # Deterministisk: poststedet gjengis ORDRETT slik det står (STOKMARKNES),
    # ikke pent-formatert som modellen ville gjort.
    assert res["data"] == {"tlf": "76118610", "sted": "STOKMARKNES"}


def test_skjema_motor_modell_uten_borealis_gir_feil(ktx, monkeypatch):
    monkeypatch.setitem(dokument_api._borealis, "status", "nede")
    res = SkjemaOperasjon({"a": "{telefon}"}, "modell").utfor(ktx)
    assert res["ok"] is False
    assert "Borealis" in res["feil"]


def test_skjema_motor_auto_faller_tilbake_uten_borealis(ktx, monkeypatch):
    """auto skal IKKE feile når modellen er nede — den gir det
    deterministiske og melder resten som ukjent."""
    monkeypatch.setitem(dokument_api._borealis, "status", "nede")
    res = SkjemaOperasjon({"tlf": "{telefon}", "navn": "{navn}"}, "auto").utfor(ktx)
    assert res["ok"] is True and res["motor"] == "auto"
    assert res["data"]["tlf"] == "76118610"
    assert res["data"]["navn"] is None
    assert res["modell_brukt"] is False


def test_skjema_motor_auto_bruker_modell_for_hull(ktx, borealis_klar, monkeypatch):
    def _stub(dok, mal):
        return {"ok": True, "skjema": {k: "Terje Karlsen" for k in mal},
                "avvik": []}
    monkeypatch.setattr(dokument_api, "fyll_skjema_kjerne", _stub)

    res = SkjemaOperasjon({"navn": "{navn}"}, "auto").utfor(ktx)
    assert res["ok"] is True
    assert res["data"]["navn"] == "Terje Karlsen"
    assert res["kilde_per_felt"]["navn"] == "modell"
    assert res["modell_brukt"] is True


def test_skjema_krever_borealis_bare_for_modell():
    assert SkjemaOperasjon({"a": "{x}"}, "modell")._krever_borealis() is True
    assert SkjemaOperasjon({"a": "{x}"}, "felter")._krever_borealis() is False
    assert SkjemaOperasjon({"a": "{x}"}, "auto")._krever_borealis() is False


# ------------------------------------------------------------------ #
#  SvarOperasjon / KorrigerOperasjon: modelldeler                     #
# ------------------------------------------------------------------ #

def test_svar_uten_borealis_gir_feil(ktx, monkeypatch):
    monkeypatch.setitem(dokument_api._borealis, "status", "nede")
    res = SvarOperasjon("Hva er beløpet?").utfor(ktx)
    assert res["ok"] is False and "Borealis" in res["feil"]


def test_svar_med_mocket_modell(ktx, borealis_klar, monkeypatch):
    sett = {}

    def _stub(tekst, sporsmal, ocr, hand, strek, strek_lest=True):
        # `strek_lest` MÅ være med i signaturen: uten den ville stubben
        # skjult at operasjonsveien glemte å sende den, og svarte
        # «ingen strekkoder funnet» om et dokument som aldri ble
        # skannet (R159). En attrapp som er mildere enn den ekte
        # funksjonen, måler mindre enn den ser ut til.
        sett["strek_lest"] = strek_lest
        return {"tom": False, "svar": "6380 kroner", "tall_verifisert": True,
                "tolket_sporsmal": sporsmal, "svar_avkortet": False,
                "advarsler": []}
    monkeypatch.setattr(dokument_api, "svar_paa_sporsmal", _stub)

    res = SvarOperasjon("Hva er beløpet?").utfor(ktx)
    assert res["ok"] is True
    assert res["svar"] == "6380 kroner"
    assert sett["strek_lest"] == ktx.strekkoder_lest, (
        "SvarOperasjon sendte ikke ktx.strekkoder_lest videre — da svarer "
        "operasjonsveien «ingen strekkoder funnet» om et uskannet dokument")


def test_korriger_uten_ocr_gir_feil(borealis_klar):
    """Har dokumentet tekstlag (ikke OCR), finnes ingen OCR-feil å rette."""
    ktx = DokumentKontekst(DOK, ocr_brukt=False)
    res = KorrigerOperasjon().utfor(ktx)
    assert res["ok"] is False
    assert "tekstlag" in res["feil"]


# ------------------------------------------------------------------ #
#  bygg_operasjon: validering av kontrakten                          #
# ------------------------------------------------------------------ #

# NB: sjekker .type, ikke isinstance — andre testmoduler kjører
# importlib.reload(dokument_api), som lager NYE klasseobjekter. En
# isinstance-sammenligning mot den importerte (før-reload) klassen ville
# da bli falsk selv om typen er riktig. .type er reload-robust.
def test_bygg_felter_og_tekst():
    assert bygg_operasjon({"type": "felter"}).type == "felter"
    assert bygg_operasjon({"type": "tekst"}).type == "tekst"
    assert bygg_operasjon({"type": "struktur"}).type == "struktur"


def test_bygg_skjema_med_motor():
    op = bygg_operasjon({"type": "skjema", "mal": {"a": "{telefon}"},
                         "motor": "auto"})
    assert op.type == "skjema" and op.motor == "auto"


def test_bygg_ukjent_type_feiler():
    with pytest.raises(ValueError, match="ukjent operasjonstype"):
        bygg_operasjon({"type": "tull"})


def test_bygg_svar_uten_sporsmal_feiler():
    with pytest.raises(ValueError, match="krever feltet 'sporsmal'"):
        bygg_operasjon({"type": "svar"})


def test_bygg_skjema_uten_mal_feiler():
    with pytest.raises(ValueError, match="krever 'mal'"):
        bygg_operasjon({"type": "skjema"})


def test_bygg_skjema_ukjent_motor_feiler():
    with pytest.raises(ValueError, match="ukjent 'motor'"):
        bygg_operasjon({"type": "skjema", "mal": {"a": "{x}"}, "motor": "tull"})


def test_bygg_uten_type_feiler():
    with pytest.raises(ValueError, match="mangler 'type'"):
        bygg_operasjon({})


# ------------------------------------------------------------------ #
#  Operasjonsmotor: flere ops, uavhengig feilhåndtering               #
# ------------------------------------------------------------------ #

def test_motoren_kjorer_flere_operasjoner(ktx):
    ops = [FelterOperasjon(),
           SkjemaOperasjon({"tlf": "{telefon}"}, "felter")]
    res = Operasjonsmotor().kjor(ktx, ops)
    assert [r["type"] for r in res] == ["felter", "skjema"]
    assert all(r["ok"] for r in res)


def test_en_operasjon_som_kaster_velter_ikke_de_andre(ktx, monkeypatch):
    class Sprengende(TekstOperasjon):
        type = "sprengende"
        def utfor(self, k):
            raise RuntimeError("boom")

    res = Operasjonsmotor().kjor(ktx, [Sprengende(), FelterOperasjon()])
    assert res[0]["ok"] is False and "boom" in res[0]["feil"]
    assert res[1]["ok"] is True          # den andre kjørte likevel


def test_deling_av_kontekst_regner_felter_en_gang(ktx, monkeypatch):
    """To operasjoner som begge trenger felter, skal dele beregningen."""
    kall = {"n": 0}
    ekte = dokument_api.utvid_entiteter

    def _teller(t, e):
        kall["n"] += 1
        return ekte(t, e)
    monkeypatch.setattr(dokument_api, "utvid_entiteter", _teller)

    # felter-motoren i skjema bruker felter_flatt (egen sti), men
    # FelterOperasjon + en annen FelterOperasjon skal dele cachen:
    Operasjonsmotor().kjor(ktx, [FelterOperasjon(), FelterOperasjon()])
    assert kall["n"] == 1
