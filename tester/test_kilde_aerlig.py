"""
«kilde» og «modell_brukt» i /dokument-svaret skal si hva som FAKTISK
skjedde.

Første funn: med skjema_motor=auto meldte /dokument «deterministisk» selv
når Borealis hadde kjørt og fylt et felt. Kilden ble utledet av BRYTEREN i
stedet for av resultatet.

Andre funn (arkitekturrevisjonen, august 2026): regelen talte en FEILET
modelldel som «modellen kjørte». En feilet del er `{ok: False, feil: …}`
og har ingen «modell_brukt» — den gamle testen `.get("modell_brukt") is
False` ga da None, og `None is False` er falskt. Resultatet var at et kall
der Borealis var NEDE meldte `kilde: "borealis+deterministisk"`.

Tredje funn: operasjoner-veien hardkodet `kilde: "motor"` uansett, så en
robot som fulgte den dokumenterte regelen leste ETHVERT operasjonssvar som
rent deterministisk.

Denne fila testet tidligere en LOKAL KOPI av regelen, og fanget derfor
ingen av de to siste feilene. Nå testes funksjonene i API-et direkte.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

from dokument_api import _delen_brukte_modellen, _modellen_kjorte


# ------------------------------------------------------------------ #
#  Én del: brukte den modellen?                                        #
# ------------------------------------------------------------------ #

def test_feilet_del_teller_ikke_som_modellbruk():
    """Kjernen i det andre funnet. Borealis nede ⇒ delen feilet ⇒
    modellen kjørte aldri, uansett hva bryteren sa."""
    assert _delen_brukte_modellen(
        {"ok": False, "feil": "Borealis er ikke klar (laster)"}) is False


def test_deterministisk_svar_teller_ikke():
    """R64: en sidelesing besvares uten modell selv om svar=ja var på."""
    assert _delen_brukte_modellen({"ok": True, "modell_brukt": False}) is False


def test_ekte_modellsvar_teller():
    assert _delen_brukte_modellen({"ok": True, "modell_brukt": True}) is True


def test_del_uten_flagg_regnes_som_modellbruk():
    """`korriger` setter ikke «modell_brukt», men kjører alltid modellen.
    Standard er derfor True — men bare når delen IKKE feilet."""
    assert _delen_brukte_modellen({"ok": True}) is True


@pytest.mark.parametrize("ikke_en_del", [None, "tekst", 42, []])
def test_manglende_del_teller_ikke(ikke_en_del):
    assert _delen_brukte_modellen(ikke_en_del) is False


# ------------------------------------------------------------------ #
#  Hele svaret: kjørte modellen?                                       #
# ------------------------------------------------------------------ #

def test_auto_som_brukte_modellen_melder_borealis():
    """Det opprinnelige funnet: auto-motoren kalte Borealis."""
    assert _modellen_kjorte({"skjema": {
        "ok": True, "motor": "auto", "modell_brukt": True,
        "kilde_per_felt": {"organisasjonsnummer": "modell"}}}) is True


def test_auto_som_beviste_alt_melder_deterministisk():
    """Motstykket: auto skal ikke overrapportere."""
    assert _modellen_kjorte({"skjema": {
        "ok": True, "motor": "auto", "modell_brukt": False,
        "kilde_per_felt": {"belop": "deterministisk"}}}) is False


def test_borealis_nede_gir_ikke_borealis_i_kilden():
    """Regresjonen fra revisjonen, i sin helhet: klienten ba om svar,
    Borealis var nede, delen feilet — kilden skal si deterministisk."""
    assert _modellen_kjorte({
        "felter": {"ok": True},
        "svar": {"ok": False, "feil": "Borealis er ikke tilgjengelig"},
    }) is False


def test_en_kjorende_del_er_nok():
    assert _modellen_kjorte({
        "svar": {"ok": False, "feil": "nede"},
        "korriger": {"ok": True},
    }) is True


def test_ingen_deler_bedt_om():
    assert _modellen_kjorte({}) is False
    assert _modellen_kjorte({"felter": {"ok": True}, "struktur": {"ok": True}}) \
        is False


# ------------------------------------------------------------------ #
#  Begge kontraktene bruker SAMME regel                                #
# ------------------------------------------------------------------ #

def test_operasjonsveien_bruker_samme_regel():
    """Operasjoner-resultatene er en liste av {type, …}. Mappet på type
    må de gi nøyaktig samme dom som bryter-veiens deler."""
    resultater = [{"type": "felter", "ok": True},
                  {"type": "svar", "ok": False, "feil": "Borealis er nede"}]
    som_deler = {r["type"]: r for r in resultater}
    assert _modellen_kjorte(som_deler) is False

    resultater[1] = {"type": "svar", "ok": True, "modell_brukt": True}
    som_deler = {r["type"]: r for r in resultater}
    assert _modellen_kjorte(som_deler) is True


def test_begge_veiene_kaller_den_ENE_regelen():
    """Vakt mot at veiene glir fra hverandre igjen: begge svarbyggerne
    skal kalle _modellen_kjorte, ingen skal regne ut kilden selv."""
    import inspect

    import dokument_api
    for metode in (dokument_api.Handler._dokument_samlet,
                   dokument_api.Handler._dokument_operasjoner):
        kilde = inspect.getsource(metode)
        assert "_modellen_kjorte(" in kilde, metode.__name__
    # og ingen av dem skal ha en egen kopi av regelen
    flat = inspect.getsource(dokument_api.Handler._dokument_samlet)
    assert 'skjema_del.get("modell_brukt")' not in flat
