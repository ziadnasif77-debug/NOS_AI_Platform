"""
Typeforventninger (R186): dokumenttypen bestemmer hva som SKAL finnes,
og rapporten sier hva som mangler — målt mot det deterministiske
uttrekket, aldri mot en gjetning.

Tre ting voktes her: at feltvokabularet er lukket (regelfila kan aldri
utvide det), at et tomt forventningssett aldri blir et bevis (R128:
`[]` er en påstand), og at rapporten er stabil i rekkefølgen.
"""
import sys

sys.path.insert(0, ".")

import pytest

from delt import typeforventninger as tf
from syntetiske_nummer import lag_fnr

GYLDIG_FNR = lag_fnr()            # bygges på kjøretid — aldri i kildekode
GYLDIG_ORGNR = "923609016"        # består mod11

FAKTURA_TEKST = ("Faktura\n"
                 "Org.nr. 923 609 016\n"
                 "Fakturadato: 12.06.2026\n"
                 "Totalt: 1 234,00 kr\n")


@pytest.fixture
def egen_regelfil(tmp_path, monkeypatch):
    """Peker modulen mot en midlertidig regelfil og nullstiller
    mtime-bufferet, så hver test ser SIN fil."""
    fil = tmp_path / "dokumenttype_forventninger.txt"

    def _pek(navn):
        assert navn == "dokumenttype_forventninger.txt"
        return str(fil)

    monkeypatch.setattr(tf, "_regelfil", _pek)
    monkeypatch.setattr(tf, "_BUFFER", None)
    return fil


# ------------------------------------------------------------------ #
#  Detektorene: lukket vokabular, påvisning — ikke gjetning           #
# ------------------------------------------------------------------ #

def test_detektorene_ser_det_som_finnes():
    struktur = {
        "dokument": {"tittel": "Faktura", "ytelse": None},
        "identifikatorer": {"fodselsnummer": [GYLDIG_FNR],
                            "kontonummer": [], "organisasjonsnummer": [],
                            "kid": [], "saksnummer": None},
        "kontakt": {"telefoner": [], "eposter": []},
        "adresser": [], "datoer": ["2026-06-12"], "perioder": [],
        "belop": [],
    }
    assert tf.FELTDETEKTORER["fodselsnummer"](struktur) is True
    assert tf.FELTDETEKTORER["dato"](struktur) is True
    assert tf.FELTDETEKTORER["tittel"](struktur) is True
    assert tf.FELTDETEKTORER["belop"](struktur) is False
    assert tf.FELTDETEKTORER["ytelse"](struktur) is False
    assert tf.FELTDETEKTORER["saksnummer"](struktur) is False


def test_alle_standardforventninger_bruker_kjente_felter():
    """Standardtabellen kan ikke forvente noe detektorene ikke kan
    påvise — da ville «mangler» vært en løgn ingen kunne motbevise."""
    for dokumenttype, felter in tf.FORVENTNINGER.items():
        for felt in felter:
            assert felt in tf.FELTDETEKTORER, (
                f"{dokumenttype} forventer «{felt}» som ingen detektor "
                "kan påvise")


# ------------------------------------------------------------------ #
#  Oppslag og rapport                                                 #
# ------------------------------------------------------------------ #

def test_ukjent_type_har_ingen_forventninger(egen_regelfil):
    assert tf.forventninger_for(None) is None
    assert tf.forventninger_for("attest") is None      # bevisst uten
    assert tf.forventningsrapport("attest", {"belop": [1]}) is None


def test_rapporten_er_stabil_og_aerlig(egen_regelfil):
    struktur = {"identifikatorer": {"fodselsnummer": [GYLDIG_FNR]},
                "datoer": [], "dokument": {"ytelse": "dagpenger"}}
    rapport = tf.forventningsrapport("vedtak", struktur)
    assert rapport["felter"] == ["fodselsnummer", "dato", "ytelse"]
    assert rapport["funnet"] == ["fodselsnummer", "ytelse"]
    assert rapport["mangler"] == ["dato"]


def test_rapport_uten_struktur_er_none(egen_regelfil):
    assert tf.forventningsrapport("vedtak", None) is None


# ------------------------------------------------------------------ #
#  Regelfila: erstatter, begrenser — utvider aldri                    #
# ------------------------------------------------------------------ #

def test_regelfila_erstatter_standarden(egen_regelfil):
    egen_regelfil.write_text("faktura = belop, kid\n", encoding="utf-8")
    assert tf.forventninger_for("faktura") == ("belop", "kid")
    # Andre typer beholder standarden sin
    assert tf.forventninger_for("vedtak") == ("fodselsnummer", "dato",
                                              "ytelse")


def test_ingen_slaar_forventningene_av(egen_regelfil):
    egen_regelfil.write_text("vedtak = ingen\n", encoding="utf-8")
    assert tf.forventninger_for("vedtak") is None
    assert tf.forventningsrapport("vedtak", {"datoer": ["x"]}) is None


def test_ukjente_felter_og_typer_hoppes_over(egen_regelfil):
    egen_regelfil.write_text(
        "faktura = belop, blodtype, dato\n"      # «blodtype» finnes ikke
        "purring = belop\n",                      # typen finnes ikke
        encoding="utf-8")
    assert tf.forventninger_for("faktura") == ("belop", "dato")
    assert tf.forventninger_for("purring") is None


def test_bare_ukjente_felter_gir_ingen_overstyring(egen_regelfil):
    """En linje der ALT er tastefeil skal ikke bli en tom forventning —
    standarden beholdes, for et tomt sett kan ikke bevise noe (R128)."""
    egen_regelfil.write_text("faktura = blodtype\n", encoding="utf-8")
    assert tf.forventninger_for("faktura") == ("belop", "dato",
                                               "organisasjonsnummer")


# ------------------------------------------------------------------ #
#  rapport_for_tekst: klassifiser og mål i ett (mellombåndets sjekk)  #
# ------------------------------------------------------------------ #

def test_komplett_faktura_har_ingen_mangler(egen_regelfil):
    rapport = tf.rapport_for_tekst(FAKTURA_TEKST)
    assert rapport["dokumenttype"] == "faktura"
    assert rapport["mangler"] == []


def test_ufullstendig_vedtak_melder_hva_som_mangler(egen_regelfil):
    rapport = tf.rapport_for_tekst("Vedtak om barnetrygd\n"
                                   "Gjelder barnetrygd.\n")
    assert rapport["dokumenttype"] == "vedtak"
    assert rapport["mangler"] == ["fodselsnummer", "dato"]


def test_tekst_uten_kjent_type_gir_ingen_rapport(egen_regelfil):
    assert tf.rapport_for_tekst("Helt alminnelig tekst om ingenting "
                                "spesielt, uten kjente typeord.") is None
    assert tf.rapport_for_tekst("") is None
