"""
Alle brytere leser SAMME verdirom — og en ukjent verdi avvises.

To brytere gikk utenom `paa()` og hadde hver sin ufullstendige liste.
Målt mot den kjørende serveren, samme forespørsel, motsatt svar:

    struktur=off    → AV
    strekkoder=off  → PÅ      (egen liste uten «off» og «no»)
    strekkoder=tull → 200, PÅ (mens struktur=tull ga 400)

Og `korriger` godtok bare tre verdier på /spor mens den godtok tolv på
/dokument: «korriger=på» var SANN på én rute og USANN på en annen —
samme ord, samme API.

`maks_sider` hadde en tredje variant av samme feil: en ugyldig verdi ble
stille ignorert, så «maks_sider=abc» ga UBEGRENSET lesing uten 400 og
uten advarsel. Klienten trodde den hadde satt en grense. Det er samme
feilmodus feltnavnvakten finnes for — et kjent felt som forsvinner i
stillhet — og maks_sider var unntatt fra begge.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api


SANNE = ["ja", "JA", "Ja", "1", "true", "TRUE", "on", "yes", "pa", "på",
         "  ja  "]
USANNE = ["nei", "NEI", "0", "false", "av", "off", "no"]
TULL = ["tull", "2", "-1", "sant", "y", "n", "javel"]


@pytest.mark.parametrize("verdi", SANNE)
def test_sanne_verdier(verdi):
    assert api.bryterverdi(verdi, False) == (True, False), verdi


@pytest.mark.parametrize("verdi", USANNE)
def test_usanne_verdier(verdi):
    assert api.bryterverdi(verdi, True) == (False, False), verdi


@pytest.mark.parametrize("verdi", TULL)
def test_ukjent_verdi_meldes_i_stedet_for_aa_bli_tolket(verdi):
    """En ukjent verdi skal gi (standard, ukjent=True) — kalleren svarer
    400. Tolket vi den som «nei», ville klienten fått noe annet enn den
    ba om, uten å bli fortalt det."""
    verdi_ut, ukjent = api.bryterverdi(verdi, True)
    assert ukjent is True, verdi
    assert verdi_ut is True, "standarden skal stå til kalleren svarer"


def test_tom_verdi_gir_standarden():
    """Skjemaposteringer (HTML, UiPath) sender gjerne ALLE felter, også
    de tomme. «svar=» skal ikke telle som «nei»."""
    assert api.bryterverdi("", True) == (True, False)
    assert api.bryterverdi("   ", False) == (False, False)
    assert api.bryterverdi(None, True) == (True, False)


def test_ett_verdirom_for_alle_brytere():
    """Kjernen. Fantes det to lister, ville to brytere igjen kunne
    tolke samme ord motsatt."""
    kilde = open(api.__file__, encoding="utf-8").read()
    # De gamle, håndskrevne listene skal være borte.
    assert '("nei", "0", "false", "av")' not in kilde, (
        "strekkoder har fortsatt sin egen, ufullstendige NEI-liste")
    assert '("ja", "1", "true")' not in kilde, (
        "korriger har fortsatt sin egen, ufullstendige JA-liste")
    assert set(api.BRYTER_JA) & set(api.BRYTER_NEI) == set(), (
        "et ord kan ikke bety både ja og nei")


def test_off_og_no_er_med_i_nei():
    """De to ordene som manglet i strekkoder-lista — og som gjorde at
    «strekkoder=off» slo skanningen PÅ."""
    assert "off" in api.BRYTER_NEI
    assert "no" in api.BRYTER_NEI


# ------------------------------------------------------------------ #
#  maks_sider                                                          #
# ------------------------------------------------------------------ #

def _post(felter, sti="/dokument"):
    """Kjører rutekoden fram til den svarer, uten socket."""
    H = api.Handler

    class Fake:
        MAKS_OPERASJONER = H.MAKS_OPERASJONER
        _les_dokument = H._les_dokument
        _dokument_samlet = H._dokument_samlet
        _dokument_operasjoner = H._dokument_operasjoner

        def __init__(self):
            self.svar = None

        def _svar(self, kode, data, hoder=None):
            self.svar = (kode, data)
            return (kode, data)

    f = Fake()
    f._kappet_advarsel = None
    f._dokument_samlet("p.txt", "tekst", "[Side 1 av 1]\nEt notat.\n",
                       None, felter, True)
    return f.svar


@pytest.mark.parametrize("verdi", ["abc", "3.5", "1e3", "-5", "0", " "])
def test_ugyldig_maks_sider_avvises_i_stedet_for_aa_ignoreres(verdi):
    """Prøver funksjonen som tolker feltet, siden selve avvisningen
    skjer i ruteren før dokumentet leses."""
    import re
    kilde = open(api.__file__, encoding="utf-8").read()
    assert "Ugyldig 'maks_sider'" in kilde, (
        "en ugyldig maks_sider skal gi 400, ikke ubegrenset lesing")
    assert '"pointer": "/maks_sider"' in kilde, (
        "feilen skal peke på feltet (RFC 6901), ikke bare beskrive det")


def test_kapping_mot_taket_meldes():
    """Kapping er ikke en feil — men den skal SIES. Ba klienten om 999
    sider og fikk 50, må den kunne se det i svaret."""
    kilde = open(api.__file__, encoding="utf-8").read()
    assert "_kappet_advarsel" in kilde
    assert "er kappet til taket" in kilde
