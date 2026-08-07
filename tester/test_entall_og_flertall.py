"""Entall og flertall skal aldri være uenige om SAMME dokument (R151).

`finn_fodselsnummer` hadde sitt eget, smalere mønster enn
`finn_alle_fodselsnummer`. Målt: av sju norske skrivemåter var fem
uenige — blant dem bindestreken, som er den vanligste av alle.

Det er ikke en kosmetisk forskjell. Flertallsvarianten fyller
`struktur.identifikatorer`; entallsvarianten fyller `felter`, og det er
`felter` som fyller `{fodselsnummer}` i en skjemamal. Samme forespørsel
svarte altså med nummeret ett sted og `null` det andre — og det tomme
feltet er det som havner i skjemaet.

Vakten sammenligner de to mot HVERANDRE, ikke mot en fasit. Da fanger
den også den motsatte skjevheten: at flertallsvarianten en dag finner
noe entallsvarianten ikke ser.
"""
import os
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from delt.tekstuttrekk import (finn_alle_fodselsnummer, finn_alle_kontonummer,
                               finn_fodselsnummer, finn_kontonummer)
from syntetiske_nummer import lag_fnr, lag_kontonummer

FNR = lag_fnr(0)
KONTO = lag_kontonummer(0)


def _skrivemaater(nr):
    """Samme verdi, slik dokumenter FAKTISK skriver den."""
    return {
        "ordrett": nr,
        "mellomrom": f"{nr[:6]} {nr[6:]}",
        "punktum": f"{nr[:4]}.{nr[4:6]}.{nr[6:]}",
        "bindestrek": f"{nr[:6]}-{nr[6:]}",
        "tankestrek": f"{nr[:6]}–{nr[6:]}",
        "linjeskift": f"{nr[:6]}\n{nr[6:]}",
        "parvis": " ".join(nr[i:i + 2] for i in range(0, 10, 2)) + nr[10],
    }


@pytest.mark.parametrize("form", sorted(_skrivemaater(FNR)))
def test_fodselsnummer_entall_og_flertall_er_enige(form):
    tekst = f"NAV Vedtak\nFodselsnummer: {_skrivemaater(FNR)[form]}\nSlutt."
    en, fl = finn_fodselsnummer(tekst), finn_alle_fodselsnummer(tekst)
    assert bool(en) == bool(fl), (
        f"«{form}»: felter={en!r} men struktur={fl!r} — "
        "samme dokument, to svar")
    assert en is None or en in fl


@pytest.mark.parametrize("form", sorted(_skrivemaater(KONTO)))
def test_kontonummer_entall_og_flertall_er_enige(form):
    tekst = f"NAV Faktura\nKontonummer: {_skrivemaater(KONTO)[form]}\nSlutt."
    en, fl = finn_kontonummer(tekst), finn_alle_kontonummer(tekst)
    assert bool(en) == bool(fl), (
        f"«{form}»: felter={en!r} men struktur={fl!r} — "
        "samme dokument, to svar")
    assert en is None or en in fl


def test_etikettregelen_gjelder_fortsatt_i_entall():
    """Enigheten skal ikke oppnås ved å slippe etikettvakten: et
    dobbeltgyldig tall under «Kontonummer:» er et KONTONUMMER, også for
    entallsvarianten."""
    tekst = f"Kontonummer: {KONTO}\n"
    assert finn_kontonummer(tekst) == KONTO
    assert finn_fodselsnummer(tekst) is None


def test_naboliming_dikter_ikke_opp_et_nummer_i_entall():
    """Dato-/beløpsvakten (R53) må gjelde begge veier — ellers ville
    enigheten vært oppnådd ved at BEGGE fant et oppdiktet nummer."""
    for tekst in ("Vedtak datert 01.01.2024 114 kroner",
                  "Fra 01.01.2024 til 02.02.2024"):
        assert finn_fodselsnummer(tekst) is None, tekst
        assert finn_alle_fodselsnummer(tekst) == [], tekst
