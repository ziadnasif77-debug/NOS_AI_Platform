"""
Operasjonene `klassifiser` (R184) og `oppsummer` (R185).

Kjernen i begge er GJENBRUK med vakter: klassifiser henter regelsvaret
fra strukturen konteksten alt har regnet ut og lar modellen bare VELGE
fra den kjente kodelisten; oppsummer sender en fast instruks gjennom
`svar_paa_sporsmal` så tallvakten og de andre vaktene gjelder også for
sammendrag. Modellen (Borealis) mockes — alt her er raskt og GPU-fritt.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import dokument_api
from dokument_api import (DokumentKontekst, KlassifiserOperasjon,
                          OppsummerOperasjon, bygg_operasjon,
                          _klassifisersvar_til_kode, _modellen_kjorte,
                          normaliser_operasjonsresultat)


DOK = ("Vedtak om barnetrygd\n"
       "HADSEL TRYGDEKONTOR\n"
       "Gjelder barnetrygd for Terje Karlsen.\n"
       "Totalt 6380.00 NOK\n")


@pytest.fixture
def ktx():
    return DokumentKontekst(DOK, ocr_brukt=True)


@pytest.fixture
def borealis_klar(monkeypatch):
    monkeypatch.setitem(dokument_api._borealis, "status", "klar")


@pytest.fixture
def borealis_nede(monkeypatch):
    monkeypatch.setitem(dokument_api._borealis, "status", "laster")


# ------------------------------------------------------------------ #
#  Fabrikken                                                          #
# ------------------------------------------------------------------ #

# NB: sjekker .type, ikke isinstance — andre testmoduler kjører
# importlib.reload(dokument_api), som lager NYE klasseobjekter (se
# test_operasjoner.py for hele forklaringen). .type er reload-robust.
def test_fabrikken_bygger_begge_typene():
    assert bygg_operasjon({"type": "klassifiser"}).type == "klassifiser"
    assert bygg_operasjon({"type": "oppsummer"}).type == "oppsummer"


def test_ukjent_type_nevner_de_nye_typene():
    """Feilmeldingen er kontrakten for hva som finnes — den skal ikke
    fortie to gyldige typer (samme ærlighetsregel som R180)."""
    with pytest.raises(ValueError, match="klassifiser, oppsummer"):
        bygg_operasjon({"type": "finnes_ikke"})


# ------------------------------------------------------------------ #
#  Kodevalidering av modellens klassifiseringssvar (R184)             #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("svar,kode", [
    ("vedtak", "vedtak"),
    ("  Vedtak.  ", "vedtak"),
    ("Legeerklæring", "legeerklaring"),      # term → kode
    ("Dokumenttype: faktura", "faktura"),    # gjentatt ledetekst
    ("ukjent", "ukjent"),
    ("vet ikke", "ukjent"),
    ("purring", None),                       # ikke i kodeverket
    ("kvitteringskopi", None),               # delstreng er IKKE treff
    ("", None),
])
def test_modellsvar_valideres_mot_kodeverket(svar, kode):
    assert _klassifisersvar_til_kode(svar) == kode


# ------------------------------------------------------------------ #
#  klassifiser: degradering, enighet, uenighet                        #
# ------------------------------------------------------------------ #

def test_klassifiser_uten_modell_gir_regelsvaret(ktx, borealis_nede):
    res = KlassifiserOperasjon().utfor(ktx)
    assert res["ok"] is True
    assert res["motor"] == "regler"
    assert res["modell_brukt"] is False
    assert res["data"]["dokumenttype"] == {"kode": "vedtak", "term": "Vedtak"}
    assert res["data"]["modell"] is None
    assert res["data"]["enige"] is None
    assert res["data"]["kilde"] == "regler"


def test_klassifiser_enige(ktx, borealis_klar, monkeypatch):
    monkeypatch.setattr(dokument_api, "klassifiser_borealis",
                        lambda tekst: ("vedtak", "vedtak"))
    res = KlassifiserOperasjon().utfor(ktx)
    assert res["motor"] == "regler+modell"
    assert res["modell_brukt"] is True
    assert res["data"]["enige"] is True
    assert res["data"]["dokumenttype"]["kode"] == "vedtak"


def test_klassifiser_uenighet_lar_regelen_avgjore(ktx, borealis_klar,
                                                  monkeypatch):
    """Uenighet er et signal til mottakeren — ikke en stille
    overstyring. Regelen har siste ord (R184)."""
    monkeypatch.setattr(dokument_api, "klassifiser_borealis",
                        lambda tekst: ("faktura", "faktura"))
    res = KlassifiserOperasjon().utfor(ktx)
    assert res["data"]["dokumenttype"]["kode"] == "vedtak"
    assert res["data"]["modell"]["kode"] == "faktura"
    assert res["data"]["enige"] is False
    assert res["data"]["kilde"] == "regler"


def test_klassifiser_modellen_avgjor_bare_naar_regelen_er_tom(
        borealis_klar, monkeypatch):
    ktx = DokumentKontekst("Ren tekst uten kjente typeord i det hele "
                           "tatt, lang nok til å ikke være tom.")
    assert (ktx.struktur.get("dokument") or {}).get("dokumenttype") is None
    monkeypatch.setattr(dokument_api, "klassifiser_borealis",
                        lambda tekst: ("brev", "brev"))
    res = KlassifiserOperasjon().utfor(ktx)
    assert res["data"]["dokumenttype"] == {"kode": "brev", "term": "Brev"}
    assert res["data"]["kilde"] == "modell"
    assert res["data"]["enige"] is None


def test_klassifiser_ugyldig_modellsvar_rapporteres(ktx, borealis_klar,
                                                    monkeypatch):
    monkeypatch.setattr(dokument_api, "klassifiser_borealis",
                        lambda tekst: (None, "purring"))
    res = KlassifiserOperasjon().utfor(ktx)
    assert res["data"]["dokumenttype"]["kode"] == "vedtak"
    assert res["data"]["modell"] is None
    assert res["data"]["modell_ugyldig"] == "purring"


def test_klassifiser_tomt_dokument_feiler_aerlig(borealis_klar):
    res = KlassifiserOperasjon().utfor(DokumentKontekst(""))
    assert res["ok"] is False


# ------------------------------------------------------------------ #
#  oppsummer: vaktene gjelder, porten gjelder                         #
# ------------------------------------------------------------------ #

def test_oppsummer_uten_modell_feiler_med_retry_signal(ktx, borealis_nede):
    res = OppsummerOperasjon().utfor(ktx)
    assert res["ok"] is False
    assert "Borealis" in res["feil"]


def test_oppsummer_gaar_gjennom_svarkjernen(ktx, borealis_klar,
                                            monkeypatch):
    """Instruksen hentes fra regler/prompter.md og HELE svar-kjernen
    brukes — det er den som bærer tallvakten (R185)."""
    sett = {}

    def _stub(tekst, sporsmal, ocr, hs, koder, lest=True):
        sett["sporsmal"] = sporsmal
        return {"tom": False, "svar": "Et vedtak om barnetrygd.",
                "modell_brukt": True, "tall_verifisert": True,
                "uverifiserte_tall": None, "tolket_sporsmal": "",
                "svar_avkortet": False, "advarsler": []}

    monkeypatch.setattr(dokument_api, "svar_paa_sporsmal", _stub)
    res = OppsummerOperasjon().utfor(ktx)
    assert res["ok"] is True
    assert res["modell_brukt"] is True
    assert res["data"]["sammendrag"] == "Et vedtak om barnetrygd."
    assert res["data"]["tall_verifisert"] is True
    assert sett["sporsmal"] == dokument_api.prompter.hent(
        "oppsummer.instruks")


def test_oppsummer_instruksen_rutes_ikke_deterministisk():
    """Ordlyden i instruksen må aldri ligne et side-, strekkode- eller
    identifikatorspørsmål — da ville den deterministiske rutingen tatt
    den, og modellen aldri fått den."""
    instruks = dokument_api.prompter.hent("oppsummer.instruks")
    assert dokument_api.kan_svares_uten_modell(instruks) is False
    assert dokument_api._sporsmalets_sideref(instruks) is None


# ------------------------------------------------------------------ #
#  Ærlighetsfeltene i konvolutten                                     #
# ------------------------------------------------------------------ #

def test_modellen_kjorte_ser_de_nye_typene():
    """`kilde: motor+borealis` er robotens raskeste ærlighetssjekk — de
    nye typene må telle med, ellers lyver toppnivået (samme klasse feil
    som R-fiksen i `_modellen_kjorte` rettet for operasjonsveien)."""
    kjorte = [normaliser_operasjonsresultat(
        {"type": "oppsummer", "ok": True, "modell_brukt": True,
         "data": {"sammendrag": "x"}})]
    assert _modellen_kjorte(kjorte) is True
    degradert = [normaliser_operasjonsresultat(
        {"type": "klassifiser", "ok": True, "motor": "regler",
         "modell_brukt": False, "data": {}})]
    assert _modellen_kjorte(degradert) is False
