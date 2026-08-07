"""Tallvakten er en sikkerhetsmekanisme — og en slik må måles.

Vakten fantes og virket, men ingen kunne svare på «hvor ofte slår den
til?». De to ytterpunktene betyr hver sin alvorlige ting:

    svært høyt aktiveringsnivå  →  modellen dikter tall
    alltid null                 →  vakten er slått av, og ingen vet det

Tre hull, målt:

1. HVILKE tall som ble stoppet sto bare som PROSA i `advarsel`. En
   klient som ville telle måtte tolke en setning — og fritekst er ikke
   en kontrakt (R132).

2. Koden gir modellen ÉN ny sjanse med strengere instruks når svaret
   har uverifiserte tall. Lyktes runde to, sto svaret som
   `tall_verifisert: true` — helt likt et svar som traff med én gang.
   En modell som trenger omskriving hver gang er en modell i trøbbel,
   og det var usynlig.

3. Ingenting ble logget, så aktiveringsnivået over tid kunne ikke
   regnes ut i det hele tatt.

FALSK BLOKKERING ER MÅLT, OG DEN ER REN
Den fryktede kostnaden — «dokumentet skriver 1 234,56, modellen svarer
1234.56, og vakten kaster en korrekt verdi» — måles nedenfor på elleve
skrivemåter. Null falske blokkeringer. Testene står her for at det skal
FORBLI slik, siden en innstramming av vakten er nettopp den endringen
som ville brutt det i stillhet.
"""
import os
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "skript"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api
from syntetiske_nummer import lag_fnr, lag_kontonummer


def _vakt(dokument, svar):
    return api.uverifiserte_tall(svar, dokument, api.dato_tokens(dokument))


# ------------------------------------------------------------------ #
#  1. Falsk blokkering — den skjulte kostnaden                         #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("dokument,svar,hva", [
    ("SUM 1 234,56 kr", "1234,56", "mellomrom fjernet"),
    ("SUM 1 234,56 kr", "1234.56", "komma → punktum"),
    ("SUM 1.234,56 kr", "1234,56", "tusenpunktum fjernet"),
    ("Belop kr 1234,56", "1 234,56", "mellomrom lagt til"),
    ("Telefon 41 28 89 03", "41288903", "gruppering fjernet"),
    ("Dato 12/06/2026", "12.06.2026", "dato normalisert"),
    ("Belop 1 234 567,00", "1234567,00", "stort tall"),
    ("SUM kr 1 234,56", "kr 1234,56", "valuta med"),
])
def test_riktig_tall_blokkeres_IKKE_av_formatforskjell(dokument, svar, hva):
    """Resultatet ser «trygt» ut når en korrekt verdi kastes — derfor
    er dette den kostnaden ingen oppdager."""
    assert _vakt(dokument, svar) == [], (
        f"{hva}: «{svar}» ble stoppet, men står i dokumentet")


def test_normaliserte_identifikatorer_slipper_gjennom():
    konto = lag_kontonummer(0)
    fnr = lag_fnr(0)
    formatert = f"{konto[:4]}.{konto[4:6]}.{konto[6:]}"
    assert _vakt(f"Kontonr {formatert}", konto) == []
    assert _vakt(f"Fodselsnummer {fnr[:6]} {fnr[6:]}", fnr) == []


# ------------------------------------------------------------------ #
#  2. …men vakten skal fortsatt stoppe det den er til for              #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("dokument,svar,hva", [
    ("SUM 268,00 og mva 28,71", "296,71", "SUMMERT av modellen"),
    ("Belop 1234,56", "1234,57", "ett siffer endret"),
    ("Dato 12.06.2026", "2026-06-24", "en helt annen dato"),
])
def test_oppdiktet_tall_stoppes(dokument, svar, hva):
    """Speilet. Uten dette kunne «null falske blokkeringer» oppnås ved
    å slå vakten av."""
    assert _vakt(dokument, svar), f"{hva}: «{svar}» slapp gjennom"


# ------------------------------------------------------------------ #
#  3. Utfallet er MASKINLESBART, ikke prosa                            #
# ------------------------------------------------------------------ #

def test_svaret_har_bade_boolen_og_detaljen():
    """Samme mønster som `mistenkt_usladdet` ved siden av
    `sladding_fullstendig` (R129): én bool å rute på, én liste å
    kontrollere."""
    skjelett = api._spor_svar()
    for felt in ("tall_verifisert", "uverifiserte_tall", "tallvakt_forsok"):
        assert felt in skjelett, felt


def test_de_nye_feltene_er_null_naar_vakten_ikke_var_innom():
    """R128: `null` = «ikke kjørt», `[]` = «kjørte og stoppet
    ingenting». En ren tekstvei går aldri via modellen."""
    skjelett = api._spor_svar()
    assert skjelett["uverifiserte_tall"] is None
    assert skjelett["tallvakt_forsok"] is None


def test_antall_forsok_skilles_fra_utfallet():
    """Det som var usynlig: et svar som traff første gang og et som
    måtte skrives om, så helt like ut."""
    import inspect
    kilde = inspect.getsource(api.svar_paa_sporsmal)
    kode = "\n".join(l.split("#")[0] for l in kilde.splitlines())
    assert "tallvakt_forsok = 1" in kode
    assert "tallvakt_forsok = 2" in kode
    assert '"tallvakt_forsok": tallvakt_forsok' in kode


def test_de_stoppede_tallene_foelger_med_i_svaret():
    import inspect
    kilde = inspect.getsource(api.svar_paa_sporsmal)
    assert '"uverifiserte_tall": list(mangler)' in kilde


# ------------------------------------------------------------------ #
#  4. Aktiveringsnivået kan FAKTISK regnes ut                          #
# ------------------------------------------------------------------ #

def test_tilgangsloggen_baerer_utfallet():
    """Uten et tall her kunne ingen svare på «hvor ofte slår vakten
    til?» — verken «modellen dikter» eller «vakten er av» kunne
    oppdages."""
    import inspect
    kilde = inspect.getsource(api._skriv_tilgang)
    assert '"tallvakt"' in kilde


def test_loggen_baerer_ALDRI_selve_tallene():
    """Et beløp eller et fødselsnummer i en logg er en lekkasje som
    overlever i sikkerhetskopier — samme grunn som at API-nøkkelen
    aldri logges. Bare ANTALL og runder."""
    import inspect
    kilde = inspect.getsource(api.Handler._do_post_intern)
    plass = kilde.find("self._tallvakt = {")
    assert plass > 0, "utfallet settes ikke"
    blokk = kilde[plass:plass + 220]
    assert '"stoppet": len(' in blokk, "antall, ikke verdiene"
    assert "uverifiserte)" not in blokk.replace("len(uverifiserte or [])", ""), (
        "selve tallene er på vei inn i loggen")


def test_openapi_beskriver_de_nye_feltene():
    spec = api._openapi()
    svar = spec["components"]["schemas"]["SvarDel"]["properties"]
    assert "uverifiserte_tall" in svar
    assert "tallvakt_forsok" in svar
    assert svar["tallvakt_forsok"]["enum"] == [1, 2]


# ------------------------------------------------------------------ #
#  Retningen som LEKKER — den forrige målingen så bare den andre       #
# ------------------------------------------------------------------ #
#
# Vakten over måler FALSK BLOKKERING: at riktige verdier ikke stoppes.
# Det er halve bildet. Den andre halvdelen — at gale verdier faktisk
# STOPPES — var umålt, og der lå feilen: `rens` strøk komma sammen med
# mellomrom og punktum, og komma er det norske desimaltegnet.
#
# «268,00» og «26800» ble dermed samme token. En modell som
# normaliserer et beløp (noe språkmodeller gjør hele tiden) slapp
# gjennom med en faktor 100 i feil, merket `tall_verifisert: true`
# og `uverifiserte_tall: []` — en POSITIV påstand om at vakten hadde
# sett etter og ikke funnet noe (R156).

MAGNITUDE = [
    ("26800", "Sum 268,00 kroner", "øre-komma strøket: faktor 100"),
    ("26 800", "Sum 268,00 kroner", "samme, med gruppering"),
    ("268,00", "Sum 26800 kroner", "motsatt vei"),
    ("12345", "Belop 123.45 USD", "punktum som desimaltegn"),
    ("1234567", "Belop 12345,67 kr", "faktor 100 på et større tall"),
]


@pytest.mark.parametrize("svar,kilde,hvorfor", MAGNITUDE)
def test_endret_magnitude_stoppes(svar, kilde, hvorfor):
    assert api.uverifiserte_tall(svar, kilde) == [svar], hvorfor


def _lovlige():
    """Kontonummeret bygges på KJØRETID — elleve siffer skrevet ut
    i fila utløser portabilitetsvakten, og den har rett."""
    konto = lag_kontonummer()
    return [
        ("268,00", "Sum 268,00 kroner", "ordrett"),
        ("23", "Belop 23,00 kroner", "R56: null øre er samme beløp"),
        ("23,00", "Belop 23 kroner", "R56 motsatt vei"),
        ("41288903", "Telefon 41 28 89 03", "gruppering med mellomrom"),
        (f"{konto[:4]}.{konto[4:6]}.{konto[6:]}", f"Konto {konto}",
         "kontonummerformat"),
        ("1 234,56", "Sum 1 234,56 kroner", "smalt hardt mellomrom"),
    ]


@pytest.mark.parametrize("svar,kilde,hvorfor", _lovlige())
def test_lovlige_verdier_slipper_fortsatt(svar, kilde, hvorfor):
    """Speilet. En vakt som stopper alt er like ubrukelig som en som
    stopper ingenting — den bare feiler i den andre retningen."""
    assert api.uverifiserte_tall(svar, kilde) == [], hvorfor


def test_endret_orebelop_stoppes_fortsatt():
    """R56 gjelder KUN når ørene er null. «23,50» er et annet beløp."""
    assert api.uverifiserte_tall("23,50", "Belop 23 kroner") == ["23,50"]
