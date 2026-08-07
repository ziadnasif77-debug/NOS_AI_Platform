"""Århundret ligger i individsifrene — og regelen har FIRE intervaller.

    000-499              1900-1999
    500-749  år 54-99    1854-1899
    500-999  år 00-39    2000-2039
    900-999  år 40-99    1940-1999   ← dette manglet

Uten det siste falt 900-999 ned i 1800-grenen. Målt mot Skatteetatens
spesifikasjon: 3802 kombinasjoner ga feil århundre, alle med nøyaktig
100 år. En født i 1975 med individnummer 950 — et intervall som er i
BRUK, fordi 000-499 er oppbrukt — kom ut av dokumentprofilen som født
1875. Hundre og femtien år gammel, uten et eneste varsel.

HVORFOR INGEN TEST KUNNE SE DET
`syntetiske_nummer.lag_fnr_fodt` genererte bare 100-499 for disse
årene. Generatoren kunne altså ikke lage nummeret som utløste feilen —
vakten var strukturelt umulig å skrive. Den fikk et `intervall`-valg,
og det er den egentlige rettingen her: en fasit som ikke kan uttrykke
feiltilfellet, måler ikke noe (R154).

OG DEN ANDRE HALVDELEN
`klassifiser_datoer` hadde nedre grense 1900 og forkastet en utledet
fødselsdato i STILLHET, mens `dokumentprofil` leverte den samme datoen.
Ett svar, to fødselsdatoer for samme person — og den ene merket
«aar_antatt: False», fordi århundret er UTLEDET av regelen og ikke
gjettet av oss. Utledet, ja. Og feil.
"""
import os
import sys
from datetime import date

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from delt.tekstuttrekk import ELDSTE_TROVERDIGE_AAR, fodselsdato_av_fnr
from syntetiske_nummer import lag_fnr_fodt


def _fasit(individ: int, aa: int):
    """Skatteetatens regel, skrevet ut for seg — ikke importert fra
    koden som prøves."""
    if individ >= 500 and aa <= 39:
        return 2000 + aa
    if 900 <= individ <= 999 and aa >= 40:
        return 1900 + aa
    if 500 <= individ <= 749 and aa >= 54:
        return 1800 + aa
    if individ <= 499:
        return 1900 + aa
    return None


def test_hele_regelen_mot_spesifikasjonen():
    """Alle lovlige kombinasjoner av individnummer og år. Meldingen
    sier HVOR MANGE og HVOR STOR feilen er — ikke «assert False»."""
    avvik = []
    for individ in range(1000):
        for aa in range(100):
            ventet = _fasit(individ, aa)
            if ventet is None:
                continue
            svar = fodselsdato_av_fnr(f"0101{aa:02d}{individ:03d}00")
            if svar and svar[2] != ventet:
                avvik.append((individ, aa, ventet, svar[2]))
    assert not avvik, (
        f"{len(avvik)} kombinasjoner ga feil århundre, "
        f"feilstørrelser: {sorted({abs(v - k) for _, _, v, k in avvik})}. "
        f"Første: individ={avvik[0][0]} år={avvik[0][1]:02d} "
        f"fasit={avvik[0][2]} kode={avvik[0][3]}")


@pytest.mark.parametrize("aar", [1940, 1954, 1975, 1999])
def test_det_hoye_individintervallet_gir_1900_tallet(aar):
    """Selve feilen, som et navngitt tilfelle per årstall. 900-999 er i
    bruk fordi 000-499 er oppbrukt — dette er ikke et kantttilfelle."""
    fnr = lag_fnr_fodt(1, 1, aar, intervall="hoy")
    assert int(fnr[6:9]) >= 900, "generatoren ga ikke et høyt individnummer"
    assert fodselsdato_av_fnr(fnr) == (1, 1, aar)


@pytest.mark.parametrize("aar", [1854, 1899])
def test_det_gamle_intervallet_gir_1800_tallet(aar):
    """Motprøven: 500-749 med år 54-99 skal FORTSATT bli 1800-tallet.
    Uten denne kunne rettingen «løst» feilen ved å flytte den."""
    fnr = lag_fnr_fodt(1, 1, aar)
    assert fodselsdato_av_fnr(fnr) == (1, 1, aar)


@pytest.mark.parametrize("aar", [1900, 1990, 2000, 2039])
def test_de_andre_intervallene_er_urort(aar):
    assert fodselsdato_av_fnr(lag_fnr_fodt(1, 1, aar)) == (1, 1, aar)


def test_de_to_veiene_er_enige_om_samme_person():
    """`dokumentprofil` og `klassifiser_datoer` leste samme nummer og
    ga to ulike svar — den ene en dato, den andre ingenting."""
    from delt import dokumentprofil
    from delt.tekstuttrekk import klassifiser_datoer

    fnr = lag_fnr_fodt(1, 1, 1975, intervall="hoy")
    fra_profil = dokumentprofil._fodselsdato_av_fnr(fnr)
    fra_datoer = [d for d in klassifiser_datoer(f"Fodselsnummer: {fnr}")
                  if d.get("type") == "fodselsdato_fra_fnr"]
    assert fra_profil == "1975-01-01"
    assert fra_datoer, (
        "klassifiser_datoer forkastet i stillhet en dato profilen leverte")
    assert fra_datoer[0]["dato"] == fra_profil


def _nummer(dag, maaned, aa, individ=100):
    """Elleve siffer bygget på KJØRETID. Skrevet ut i fila ville de
    utløst portabilitetsvakten — og den har rett: elleve siffer ser ut
    som et fødselsnummer uansett hva de er ment å være."""
    return f"{dag:02d}{maaned:02d}{aa:02d}{individ:03d}00"


def test_h_nummer_leses_ogsaa():
    """Hjelpenummer fra helsevesenet legger 40 til MÅNEDEN. Uten dette
    ga fødselsdatoen None — trygt, men tapt i stillhet."""
    assert fodselsdato_av_fnr(_nummer(1, 41, 90)) is not None


def test_29_februar_i_ikke_skuddaar_er_ingen_dato():
    """Uten kontrollen bygget dokumentprofilen strengen «1901-02-29»,
    og `date.fromisoformat` hos klienten kastet ValueError på et felt
    serveren nettopp hadde levert som gyldig."""
    assert fodselsdato_av_fnr(_nummer(29, 2, 1)) is None
    with pytest.raises(ValueError):
        date(1901, 2, 29)


def test_29_februar_i_skuddaar_er_en_dato():
    """Motprøven — kontrollen skal ikke forkaste lovlige datoer."""
    assert fodselsdato_av_fnr(_nummer(29, 2, 96)) == (29, 2, 1996)


def test_nedre_grense_folger_regelen_ikke_et_rundt_tall():
    """1854 fordi det er der regelen begynner. 1900 var et rundt tall
    som forkastet det regelen selv kunne produsere."""
    assert ELDSTE_TROVERDIGE_AAR == 1854
