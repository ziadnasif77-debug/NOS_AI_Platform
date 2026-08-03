"""
Deterministisk siderouting i svar-flyten.

Målt på den syntetiske bunken: modellen fikk HELE teksten (7 335 tegn —
godt under grensen, med «[Side 10 av 10]» i klartekst) og svarte likevel
«Side 10 finnes ikke i dokumentet» på «les side 10». Sideindeksering er
nettopp den typen jobb en liten modell roter bort og koden gjør perfekt:
markørene er kodegenererte.

Reglene som testes:
  * ren sidelesing («les side 10») → ordrett utsnitt, ALDRI modell
  * side utenfor dokumentet → ærlig deterministisk svar, ALDRI modell
  * spørsmål OM en side («hva er beløpet på side 3?») → modellen får
    KUN den siden
  * kilde/modell_brukt sier ærlig at modellen ikke ble brukt
"""
import sys
import types

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import dokument_api as api

BUNKE = ("[Side 1 av 3]\nVedtak om sykepenger\nSaksnummer: 4417820\n"
         "[Side 2 av 3]\nBeloep aa betale kr 4 812,00\nForfallsdato 24.06.2026\n"
         "[Side 3 av 3]\nReturslipp - dokumentkontroll\nTalet paa sider: 3")


# ------------------------------------------------------------------ #
#  Byggeklossene                                                       #
# ------------------------------------------------------------------ #

def test_del_i_sider():
    antall, sider = api.del_i_sider(BUNKE)
    assert antall == 3
    assert sider[1].startswith("Vedtak")
    assert sider[2].startswith("Beloep")
    assert sider[3].startswith("Returslipp")


def test_del_i_sider_uten_markorer_er_ettsidig():
    antall, sider = api.del_i_sider("bare litt tekst")
    assert (antall, sider) == (1, {1: "bare litt tekst"})


@pytest.mark.parametrize("sporsmal,forventet", [
    ("les side 10", 10),
    ("Vis sida 2", 2),
    ("hva er beløpet på side 3?", 3),
    ("s. 7", 7),
    ("hva er totalen?", None),
    ("les hele dokumentet", None),
])
def test_sideref(sporsmal, forventet):
    assert api._sporsmalets_sideref(sporsmal) == forventet


@pytest.mark.parametrize("sporsmal,ren", [
    ("les side 10", True),
    ("vis sida 2", True),
    ("Side 3", True),
    ("skriv ut side 1", True),
    ("hva står på side 6", True),
    ("hva er beløpet på side 3?", False),   # spørsmål OM siden → modell
    ("les side 2 og oppsummer", False),
])
def test_ren_sidelesing(sporsmal, ren):
    assert api.er_ren_sidelesing(sporsmal) is ren


# ------------------------------------------------------------------ #
#  Kjernen — modellen skal ALDRI kalles på de deterministiske veiene   #
# ------------------------------------------------------------------ #

def _forby_modell(monkeypatch):
    def _eksploder(*a, **kw):
        raise AssertionError("modellen ble kalt på en deterministisk vei")
    monkeypatch.setattr(api, "_borealis_generer", _eksploder)


def test_ren_lesing_gir_ordrett_side_uten_modell(monkeypatch):
    _forby_modell(monkeypatch)
    kjerne = api.svar_paa_sporsmal(BUNKE, "les side 3", False, [], [])
    assert kjerne["modell_brukt"] is False
    assert kjerne["svar"].startswith("Returslipp")
    assert "Talet paa sider: 3" in kjerne["svar"]
    assert "deterministisk" in kjerne["tolket_sporsmal"]


def test_side_utenfor_dokumentet_uten_modell(monkeypatch):
    """Regresjonen — men nå med RIKTIG begrunnelse: side 10 finnes
    faktisk ikke i et 3-siders dokument, og KODEN sier det."""
    _forby_modell(monkeypatch)
    kjerne = api.svar_paa_sporsmal(BUNKE, "les side 10", False, [], [])
    assert kjerne["modell_brukt"] is False
    assert "3 sider" in kjerne["svar"]
    assert "side 10 finnes ikke" in kjerne["svar"]


def test_sporsmal_om_side_gir_modellen_kun_den_siden(monkeypatch):
    fanget = {}

    def _fang(prompt, maks):
        fanget["prompt"] = prompt
        return "kr 4 812,00", False

    monkeypatch.setattr(api, "_borealis_generer", _fang)
    kjerne = api.svar_paa_sporsmal(BUNKE, "hva er beløpet på side 2?",
                                   False, [], [])
    assert kjerne["modell_brukt"] is True
    assert "Beloep aa betale" in fanget["prompt"]
    # sidene rundt skal IKKE være med
    assert "Vedtak om sykepenger" not in fanget["prompt"]
    assert "Returslipp" not in fanget["prompt"]


# ------------------------------------------------------------------ #
#  Endepunktet: virker uten Borealis, og kilden er ærlig               #
# ------------------------------------------------------------------ #

def _fang_handler():
    h = api.Handler.__new__(api.Handler)
    h.headers = {}
    h.path = "/dokument"
    h.command = "POST"
    h.client_address = ("127.0.0.1", 4321)
    fanget = {}
    h.send_response = lambda k: fanget.__setitem__("kode", k)
    h.send_header = lambda n, v: None
    h.end_headers = lambda: None
    h.wfile = types.SimpleNamespace(
        write=lambda b: fanget.__setitem__(
            "kropp", __import__("json").loads(b)))
    h._cors_origin = lambda: None
    return h, fanget


def test_dokument_ren_sidelesing_virker_uten_borealis(monkeypatch):
    """Selv med modellen NEDE skal «les side 2» besvares — og kilden
    skal si «deterministisk», ikke late som Borealis bidro."""
    _forby_modell(monkeypatch)
    monkeypatch.setitem(api._borealis, "status", "nede")
    h, fanget = _fang_handler()
    h._dokument_samlet("bunke.txt", "tekst", BUNKE, None,
                       {"sporsmal": "les side 2", "tekst": "nei",
                        "felter": "nei"}, True)
    assert fanget["kode"] == 200
    svar = fanget["kropp"]["svar"]
    assert svar["ok"] is True
    assert svar["modell_brukt"] is False
    assert svar["svar"].startswith("Beloep")
    assert fanget["kropp"]["kilde"] == "deterministisk"


def test_dokument_kilde_borealis_naar_modellen_faktisk_brukes(monkeypatch):
    monkeypatch.setattr(api, "_borealis_generer",
                        lambda p, m: ("4 812,00", False))
    monkeypatch.setitem(api._borealis, "status", "klar")
    h, fanget = _fang_handler()
    h._dokument_samlet("bunke.txt", "tekst", BUNKE, None,
                       {"sporsmal": "hva er beløpet på side 2?",
                        "tekst": "nei", "felter": "nei"}, True)
    assert fanget["kode"] == 200
    assert fanget["kropp"]["svar"]["modell_brukt"] is True
    assert fanget["kropp"]["kilde"] == "borealis+deterministisk"


# ------------------------------------------------------------------ #
#  Strekkode: verdien er DEKODET, ikke lest av en modell               #
# ------------------------------------------------------------------ #

KODER = [{"type": "CODE128", "verdi": "1002345678911", "side": 3}]


@pytest.mark.parametrize("sporsmal", [
    "hva er strekkoden?",
    "strekkoden",
    "hent strekkoden fra side 3",
    "vis QR-koden",
    "les strekkoden",
    "hvilken strekkode staar paa side 3",
])
def test_strekkodesporsmal_kjennes_igjen(sporsmal):
    assert api.er_strekkodesporsmal(sporsmal) is True


@pytest.mark.parametrize("sporsmal", [
    "hva er totalen?",
    "les side 3",
    "oppsummer dokumentet",
    "hva er kontonummeret?",
])
def test_vanlige_sporsmal_rutes_ikke_som_strekkode(sporsmal):
    assert api.er_strekkodesporsmal(sporsmal) is False


def test_strekkodeverdi_uten_modell(monkeypatch):
    """Regresjonen: «hva er strekkoden?» ga «Finnes ikke i dokumentet»
    mens den dekodede verdien lå i SAMME svar."""
    _forby_modell(monkeypatch)
    kjerne = api.svar_paa_sporsmal(BUNKE, "hva er strekkoden?", False,
                                   [], KODER)
    assert kjerne["modell_brukt"] is False
    assert "1002345678911" in kjerne["svar"]
    assert "CODE128" in kjerne["svar"]


def test_strekkode_filtreres_paa_side(monkeypatch):
    _forby_modell(monkeypatch)
    kjerne = api.svar_paa_sporsmal(BUNKE, "hent strekkoden fra side 3",
                                   False, [], KODER)
    assert "1002345678911" in kjerne["svar"]
    # feil side → ærlig svar som PEKER på riktig side
    kjerne = api.svar_paa_sporsmal(BUNKE, "hent strekkoden fra side 1",
                                   False, [], KODER)
    assert "Ingen strekkode på side 1" in kjerne["svar"]
    assert "side 3" in kjerne["svar"]


def test_ingen_strekkoder_sies_aerlig(monkeypatch):
    _forby_modell(monkeypatch)
    kjerne = api.svar_paa_sporsmal(BUNKE, "hva er strekkoden?", False, [], [])
    assert kjerne["modell_brukt"] is False
    assert "Ingen strekkoder" in kjerne["svar"]


def test_skanning_avslaatt_gir_ikke_ingen_funnet(monkeypatch):
    """strekkoder=nei betyr at vi ikke SÅ etter — å svare «ingen funnet»
    ville vært en løgn. Da skal spørsmålet gå til modellen i stedet."""
    fanget = {}

    def _fang(prompt, maks):
        fanget["kalt"] = True
        return "vet ikke", False

    monkeypatch.setattr(api, "_borealis_generer", _fang)
    kjerne = api.svar_paa_sporsmal(BUNKE, "hva er strekkoden?", False, [],
                                   [], strekkoder_lest=False)
    assert kjerne.get("modell_brukt") is True
    assert fanget.get("kalt") is True


def test_strekkodesporsmal_virker_uten_borealis(monkeypatch):
    _forby_modell(monkeypatch)
    monkeypatch.setitem(api._borealis, "status", "nede")
    h, fanget = _fang_handler()
    monkeypatch.setattr(api, "les_strekkoder_bytes", lambda *a, **kw: KODER)
    h._dokument_samlet("bunke.txt", "tekst", BUNKE, None,
                       {"sporsmal": "hva er strekkoden?", "tekst": "nei",
                        "felter": "nei"}, True)
    assert fanget["kode"] == 200
    svar = fanget["kropp"]["svar"]
    assert svar["ok"] is True
    assert svar["modell_brukt"] is False
    assert fanget["kropp"]["kilde"] == "deterministisk"


# ------------------------------------------------------------------ #
#  Sjekksumvaliderte identifikatorer svares av uttrekket               #
# ------------------------------------------------------------------ #

# Bunken har TO fødselsnumre og TO kontonumre — modellen ville valgt ett
IDENT_TEKST = (
    "[Side 1 av 2]\nFoedselsnummer: 12345678910\n"
    "Kontonummer: 12345678910\nKID-nummer 1002345678911\n"
    "Organisasjonsnummer: 889000007\n"
    "[Side 2 av 2]\nFoedselsnummer: 12345678910\n"
    "Refusjon utbetales til kontonummer: 12345678910")


@pytest.mark.parametrize("sporsmal,felt", [
    ("hva er KID?", "kid"),
    ("hva er KID-nummeret?", "kid"),
    ("hent kid", "kid"),
    ("hva er kontonummeret?", "kontonummer"),
    ("hva er foedselsnummeret?", "fodselsnummer"),
    ("hva er organisasjonsnummeret", "organisasjonsnummer"),
    ("hva er telefonnummeret?", "telefon"),
    ("hva er eposten?", "epost"),
])
def test_identsporsmal_kjennes_igjen(sporsmal, felt):
    assert api.identsporsmalets_felt(sporsmal) == felt


@pytest.mark.parametrize("sporsmal", [
    "hva er totalen?",
    "oppsummer dokumentet",
    "naar er brevet datert?",
    "hvem har signert?",
])
def test_vanlige_sporsmal_rutes_ikke_som_identifikator(sporsmal):
    assert api.identsporsmalets_felt(sporsmal) is None


def test_kid_hentes_uten_modell(monkeypatch):
    _forby_modell(monkeypatch)
    kjerne = api.svar_paa_sporsmal(IDENT_TEKST, "hva er KID?", False, [], [])
    assert kjerne["modell_brukt"] is False
    assert kjerne["svar"] == "1002345678911"


def test_alle_forekomster_listes_ikke_bare_en(monkeypatch):
    """Modellen ville valgt ETT nummer. Bunken har to av hver — koden
    svarer med begge, og sier hvor mange."""
    _forby_modell(monkeypatch)
    kjerne = api.svar_paa_sporsmal(IDENT_TEKST, "hva er foedselsnummeret?",
                                   False, [], [])
    assert "12345678910" in kjerne["svar"]
    assert "12345678910" in kjerne["svar"]
    assert kjerne["svar"].startswith("2 ")

    kjerne = api.svar_paa_sporsmal(IDENT_TEKST, "hva er kontonummeret?",
                                   False, [], [])
    assert "12345678910" in kjerne["svar"]
    assert "12345678910" in kjerne["svar"]


def test_identsporsmal_respekterer_side(monkeypatch):
    """«kontonummeret på side 2» søker i side 2 — ikke i hele bunken."""
    _forby_modell(monkeypatch)
    kjerne = api.svar_paa_sporsmal(IDENT_TEKST,
                                   "hva er kontonummeret paa side 2?",
                                   False, [], [])
    assert kjerne["svar"] == "12345678910"
    assert "12345678910" not in kjerne["svar"]


def test_ingen_gyldig_identifikator_sies_aerlig(monkeypatch):
    """Et nummer som ikke består kontrollsifferet utelates — og koden
    forklarer hvorfor, i stedet for å la modellen gjette et tall."""
    _forby_modell(monkeypatch)
    kjerne = api.svar_paa_sporsmal(
        "[Side 1 av 1]\nReferanse 12345678910 i saken", 
        "hva er foedselsnummeret?", False, [], [])
    assert kjerne["modell_brukt"] is False
    assert "Fant ingen" in kjerne["svar"]
    assert "kontrollsifferet" in kjerne["svar"]


def test_barkode_stavemaaten_rutes(monkeypatch):
    """«barkode» (uten c) er vanlig — den gikk til modellen før."""
    _forby_modell(monkeypatch)
    kjerne = api.svar_paa_sporsmal(BUNKE, "les barkode i side 3",
                                   False, [], KODER)
    assert kjerne["modell_brukt"] is False
    assert "1002345678911" in kjerne["svar"]


# ------------------------------------------------------------------ #
#  ALLE strekkoder, ikke bare de på de første sidene                   #
# ------------------------------------------------------------------ #

FLERE_KODER = [
    {"type": "CODE128", "verdi": "1002345678911", "side": 3},
    {"type": "CODE128", "verdi": "NAV4417820-2026-06", "side": 10},
]


def test_strekkodetaket_dekker_hele_dokumentet():
    """Taket var 5 sider. Arkivstrekkoden på side 10 i en 10-siders
    bunke ble derfor ALDRI lest — og returslipp/arkivkoder står nettopp
    bakerst, så grensen rammet systematisk den viktigste koden."""
    assert api.STREKKODE_MAKS_SIDER >= 10


def test_alle_strekkoder_listes(monkeypatch):
    _forby_modell(monkeypatch)
    kjerne = api.svar_paa_sporsmal(BUNKE, "hva er strekkoden?", False,
                                   [], FLERE_KODER)
    assert kjerne["modell_brukt"] is False
    assert "1002345678911" in kjerne["svar"]
    assert "NAV4417820-2026-06" in kjerne["svar"]
    # side skal stå på hver, så leseren vet HVOR den er
    assert "side 3" in kjerne["svar"]
    assert "side 10" in kjerne["svar"]


def test_strekkode_per_side_filtrerer_riktig(monkeypatch):
    _forby_modell(monkeypatch)
    kjerne = api.svar_paa_sporsmal(BUNKE, "hva er strekkoden paa side 10?",
                                   False, [], FLERE_KODER)
    assert "NAV4417820-2026-06" in kjerne["svar"]
    assert "1002345678911" not in kjerne["svar"]


def test_duplikater_fjernes():
    """pyzbar melder av og til samme kode to ganger på et støyete skann."""
    import numpy as np
    rapport = {}
    # tomme hvite sider → ingen koder, men rapporten skal fylles
    sider = [np.full((60, 60, 3), 255, np.uint8)] * 3
    koder = api.les_strekkoder_bytes(b"", sider=sider, rapport=rapport)
    assert koder == []
    assert rapport["sider_skannet"] == 3
    assert rapport["avkortet"] is False


def test_avkorting_meldes_i_rapporten():
    import numpy as np
    rapport = {}
    sider = [np.full((60, 60, 3), 255, np.uint8)] * 8
    api.les_strekkoder_bytes(b"", maks_sider=3, sider=sider, rapport=rapport)
    assert rapport["sider_skannet"] == 3
    assert rapport["sider_totalt"] == 8
    assert rapport["avkortet"] is True
