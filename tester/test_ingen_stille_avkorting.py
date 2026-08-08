"""Et avkortet resultat skal ALDRI leveres som et helt (R160).

Systemet har mønsteret på plass overalt ellers — `svar_avkortet`,
`strekkode_rapport.avkortet`, `sider_lest/sider_totalt`. Korrigeringen
var unntaket:

    27 383 tegn inn  →  3 000 tegn ut  →  null merker

Modellen fikk bare de første 3 000 tegnene, så den kunne bare rette de
første 3 000. Resten forsvant. Og `_linjevakt` — vakten som skal stoppe
at modellen skriver om teksten — gjorde det verre: den sammenlignet det
avkortede svaret med HELE originalen, fant ulikt linjeantall, og
returnerte kandidaten urørt. Vakten slapp altså avkortingen gjennom
fordi den ikke kjente den igjen.

Ingen advarsel. Brukeren lagret den «korrigerte» teksten som sin
reviderte kopi av dokumentet.
"""
import os
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "skript"))

import dokument_api as api

LANG = "Vedtak om sykepenger. Beloep 4812,00 kroner. " * 700
KORT = "Vedtak om sykepenger. Beloep 4812,00 kroner."


@pytest.fixture
def modell(monkeypatch):
    """En modell som svarer noe helt annet enn originalen — så testen
    måler hva KODEN gjør med svaret, ikke hva modellen skrev."""
    monkeypatch.setattr(api, "_borealis_generer",
                        lambda p, m: ("RETTET TEKST", False))


def test_ingenting_forsvinner_fra_et_langt_dokument(modell):
    ut = api.korriger_borealis(LANG)
    assert LANG[-60:] in ut, (
        f"halen forsvant: {len(LANG)} tegn inn, {len(ut)} tegn ut")


def test_avkortingen_er_MERKET(modell):
    """Det holder ikke at teksten er der — leseren må se hvor
    rettingen slutter og den rå teksten begynner."""
    ut = api.korriger_borealis(LANG)
    assert "KORRIGERINGEN DEKKER" in ut
    assert str(api.KORRIGER_MAKS_TEGN) in ut


def test_et_kort_dokument_faar_ingen_merkelapp(modell):
    """Speilet. En merkelapp på hvert eneste svar ville vært like
    ubrukelig som ingen."""
    ut = api.korriger_borealis(KORT)
    assert "KORRIGERINGEN DEKKER" not in ut


def test_vinduet_har_et_navn_og_kan_settes():
    """En naken 3000-er inne i funksjonen var usynlig for alle som
    skulle drifte dette."""
    assert api.KORRIGER_MAKS_TEGN == 3000


def test_linjevakten_maaler_mot_det_modellen_FIKK_SE(monkeypatch):
    """Kjernen i hvorfor feilen overlevde: vakten sammenlignet svaret
    med HELE originalen. På et langt dokument var linjeantallet alltid
    ulikt, så vakten ga opp og returnerte kandidaten urørt — hver
    eneste gang."""
    sett = {}

    def _falsk_linjevakt(original, kandidat):
        sett["original_lengde"] = len(original)
        return kandidat

    monkeypatch.setattr(api, "_linjevakt", _falsk_linjevakt)
    monkeypatch.setattr(api, "_borealis_generer",
                        lambda p, m: ("RETTET TEKST", False))
    api.korriger_borealis(LANG)
    assert sett["original_lengde"] <= api.KORRIGER_MAKS_TEGN, (
        "linjevakten fikk hele originalen, ikke den delen modellen så — "
        "da kan den aldri pare linjene og gir alltid opp")


def test_selvkontrollen_sammenligner_samme_grunnlag(monkeypatch):
    """Pass 2 fikk `ocr_tekst[:3000]` og `forste[:3000]`. Med et
    navngitt vindu er de to garantert like store."""
    promptene = []
    monkeypatch.setattr(api, "_borealis_generer",
                        lambda p, m: (promptene.append(p), ("ANNET", False))[1])
    api.korriger_borealis(LANG)
    assert len(promptene) == 2, "selvkontrollpasset kjørte ikke"
