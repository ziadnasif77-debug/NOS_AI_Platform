"""
«kilde» i /dokument-svaret skal si hva som FAKTISK skjedde.

Funnet da brukeren spurte hvilke brytere som bruker modellen: med
skjema_motor=auto meldte /dokument «kilde: deterministisk» selv når
Borealis hadde kjørt og fylt et felt (kilde_per_felt viste «modell», og
kallet tok 0,9 s). Grunnen var at kilden ble utledet av BRYTEREN
(skjema_motor == "modell") i stedet for av resultatet.

Det gjorde det umulig for klienten å skille et BEVIST svar fra et
GJETTET — nettopp skillet hele arkitekturen er bygget rundt.
/fyll_skjema gjorde det allerede riktig via «modell_brukt».

Ren logikk på svarsammensetningen — ingen socket, ingen modell.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest


def _kilde(vil_ha_modell: bool, skjema_del) -> str:
    """Speiler regelen i dokument_api._svar_dokument. Holdes bevisst kort
    slik at testen tester REGELEN, ikke hele HTTP-veien."""
    modell_kjorte = vil_ha_modell or (isinstance(skjema_del, dict)
                                      and skjema_del.get("modell_brukt"))
    return "borealis+deterministisk" if modell_kjorte else "deterministisk"


def test_auto_som_brukte_modellen_melder_borealis():
    """Regresjonen: auto-motoren kalte Borealis, men svaret sa
    «deterministisk»."""
    auto_med_modell = {"ok": True, "motor": "auto", "modell_brukt": True,
                       "kilde_per_felt": {"organisasjonsnummer": "modell"}}
    assert _kilde(False, auto_med_modell) == "borealis+deterministisk"


def test_auto_som_beviste_alt_melder_deterministisk():
    """Motstykket: auto skal IKKE overrapportere. Klarte den alt med
    regler, kjørte ingen modell — og da er svaret deterministisk."""
    auto_uten_modell = {"ok": True, "motor": "auto", "modell_brukt": False,
                        "kilde_per_felt": {"belop": "deterministisk"}}
    assert _kilde(False, auto_uten_modell) == "deterministisk"


@pytest.mark.parametrize("skjema_del", [
    None,                                        # skjema ikke bedt om
    {"ok": True, "motor": "felter"},             # ren fletting, ingen flagg
    {"ok": False, "feil": "noe gikk galt"},      # feilet del
])
def test_uten_modellbruk_er_kilden_deterministisk(skjema_del):
    assert _kilde(False, skjema_del) == "deterministisk"


@pytest.mark.parametrize("skjema_del", [None, {"ok": True, "motor": "felter"}])
def test_sporsmal_eller_korriger_melder_alltid_borealis(skjema_del):
    """svar/korriger/motor=modell setter vil_ha_modell — uendret oppførsel."""
    assert _kilde(True, skjema_del) == "borealis+deterministisk"


def test_regelen_er_den_samme_som_i_api_et():
    """Vakt mot at testen og koden glir fra hverandre: hent regelen fra
    modulen og sjekk at den fortsatt leser modell_brukt."""
    import inspect

    import dokument_api
    kilde = inspect.getsource(dokument_api.Handler._dokument_samlet)
    assert "modell_kjorte" in kilde
    assert 'skjema_del.get("modell_brukt")' in kilde
