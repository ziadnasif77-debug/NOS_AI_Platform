"""
Regresjonstester for fase 1 i arkitekturrevisjonen (docs/api_revisjon_2026-08.md).

Alle feilene her ga GALE SVAR som så riktige ut — ingen av dem hadde en
feilmelding ved siden av seg. Det er den farlige sorten, og derfor har
hver av dem nå en test som beskriver den konkrete skaden.
"""
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

from delt.saksfelter import finn_utbetalt_belop
from delt.tekstuttrekk import (er_gyldig_fnr, er_gyldig_kontonummer,
                               felter_flatt, finn_adresser,
                               finn_dokumentdato, finn_fodselsnummer,
                               finn_kontonummer, finn_postnummer_sted,
                               gjelder_periode, klassifiser_datoer,
                               sett_dato_roller, strukturert_uttrekk)


def _dobbeltgyldig() -> str:
    """Et tall som består BÅDE fnr- og kontosjekksummen. Slike finnes i
    virkeligheten, og de er hele grunnen til at etiketten må avgjøre."""
    for individ in range(100, 1000):
        kandidat = f"010190{individ:03d}"
        for k1 in range(10):
            for k2 in range(10):
                nr = f"{kandidat}{k1}{k2}"
                if er_gyldig_fnr(nr) and er_gyldig_kontonummer(nr):
                    return nr
    raise AssertionError("fant ikke et dobbeltgyldig nummer")


DOBBEL = _dobbeltgyldig()


# ------------------------------------------------------------------ #
#  F1.1 — entallsfinnerne manglet etikettvakten                        #
# ------------------------------------------------------------------ #

def test_merket_konto_rapporteres_ikke_som_fodselsnummer():
    """Skaden: `felter.fodselsnummer` returnerte BANKKONTOEN, og verdien
    gikk videre inn i skjemautfyllingen via felter_flatt — så en mal med
    {fodselsnummer} ble fylt med et kontonummer."""
    tekst = f"Refusjon utbetales til\nKontonummer: {DOBBEL}"
    assert finn_fodselsnummer(tekst) is None
    assert finn_kontonummer(tekst) == DOBBEL


def test_merket_fodselsnummer_er_fortsatt_fodselsnummer():
    tekst = f"Fodselsnummer: {DOBBEL}"
    assert finn_fodselsnummer(tekst) == DOBBEL
    assert finn_kontonummer(tekst) is None


def test_entalls_og_flertallsfinnerne_er_enige():
    """De to svarte MOTSATT på samme tall i samme dokument."""
    tekst = f"Refusjon utbetales til\nKontonummer: {DOBBEL}"
    ident = strukturert_uttrekk(tekst)["identifikatorer"]
    assert finn_fodselsnummer(tekst) is None
    assert ident["fodselsnummer"] == []
    assert finn_kontonummer(tekst) == DOBBEL
    assert ident["kontonummer"] == [DOBBEL]


def test_flat_tabell_far_samme_svar():
    flat = felter_flatt(f"Refusjon utbetales til\nKontonummer: {DOBBEL}")
    assert flat["fodselsnummer"] is None
    assert flat["kontonummer"] == DOBBEL


# ------------------------------------------------------------------ #
#  F1.2 — prosentvakten dekket «prosent», men ikke «%»                 #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("tekst", [
    "du faar utbetalt 100 prosent av dette",
    "du faar utbetalt 100 % av dette",
    "du faar utbetalt 100% av dette",
    "du faar utbetalt 100 pst. av dette",
])
def test_prosentandel_blir_aldri_et_belop(tekst):
    """«\\b» bak «%» krever et ordtegn, og etter «%» kommer et mellomrom.
    Halve fiksen virket: «prosent» ble avvist, «%» slapp gjennom — og
    det er kilden til utbetalt_belop = 100.0 i et ekte svar."""
    assert finn_utbetalt_belop(tekst) is None, tekst


def test_ekte_belop_finnes_fortsatt():
    assert finn_utbetalt_belop("Utbetalt: kr 74 040,00") == 74040.00


def test_letingen_fortsetter_forbi_prosenten():
    assert finn_utbetalt_belop(
        "utbetalt 100 % av grunnlaget. Utbetalt beloep: kr 74 040,00") \
        == 74040.00


# ------------------------------------------------------------------ #
#  F1.3 — selskapsformvakten kom bare i den ene adressefinneren        #
# ------------------------------------------------------------------ #

FIRMALINJE = ("Arbeidsgiver: Rema 1000 AS, Org. nr. 923 609 016\n"
              "Storgata 14 B\n3044 DRAMMEN")


def test_firmanavn_blir_ikke_postnummer_i_noen_av_finnerne():
    """`felter.postnummer/poststed` sa 1000 / AS mens
    `struktur.adresser` sa 3044 / DRAMMEN — i samme svar. Og det er den
    første som mater {postnummer} i en mal."""
    assert finn_postnummer_sted(FIRMALINJE) == ("3044", "DRAMMEN")
    assert finn_adresser(FIRMALINJE) == [
        {"gate": "Storgata 14 B", "postnummer": "3044", "poststed": "DRAMMEN"}]


def test_postboksvakten_star_uendret():
    assert finn_postnummer_sted("Postboks 6600 Etterstad\n0607 OSLO") \
        == ("0607", "OSLO")


# ------------------------------------------------------------------ #
#  F1.5 — «periode_start» betydde to ulike ting                        #
# ------------------------------------------------------------------ #

BUNKE_MED_PERIODE = """[Side 1 av 2]
Vedtak om sykepenger
Vedtaksdato: 28.05.2026
Sykepenger for perioden 02.04.2026 til og med 17.04.2026.
Ansatt fra: 01.08.2019
[Side 2 av 2]
Utstedt: 30.09.2026
"""


def test_periode_betyr_det_samme_i_profil_og_mal():
    """Profilen mente «perioden dokumentet gjelder for», felter_flatt
    mente «datospennet i bunken». Samme navn, ulik verdi, samme svar."""
    from delt.dokumentprofil import bygg_profil
    datoer = sett_dato_roller(klassifiser_datoer(BUNKE_MED_PERIODE))
    profil = bygg_profil(BUNKE_MED_PERIODE, datoer_detaljert=datoer,
                         dokumentdato=finn_dokumentdato(datoer))
    flat = felter_flatt(BUNKE_MED_PERIODE)

    assert profil["dokument"]["periode_start"] == "2026-04-02"
    assert flat["periode_start"] == "02.04.2026"       # samme dato, norsk form
    assert profil["dokument"]["periode_slutt"] == "2026-04-17"
    assert flat["periode_slutt"] == "17.04.2026"


def test_bunkespennet_har_fatt_sine_egne_navn():
    """Spennet forsvant ikke — det heter noe annet nå, som det skal."""
    flat = felter_flatt(BUNKE_MED_PERIODE)
    assert flat["dokumentspenn_fra"] == "01.08.2019"
    assert flat["dokumentspenn_til"] == "30.09.2026"
    assert flat["dokumentspenn_fra"] != flat["periode_start"]


def test_gjelder_periode_har_en_kilde():
    """Profilen og skjemautfyllingen skal kalle SAMME funksjon."""
    from delt import dokumentprofil
    from delt import tekstuttrekk
    assert dokumentprofil.gjelder_periode is tekstuttrekk.gjelder_periode


# ------------------------------------------------------------------ #
#  F1.6 — dokumentdatoen ble regnet av en AVKORTET liste               #
# ------------------------------------------------------------------ #

def _mange_datoer_med_vedtak_bakerst() -> str:
    """41 datoer der vedtaksdatoen står SIST — vanlig i en bunke der
    vedtaket ligger bakerst."""
    linjer = [f"Frist {d:02d}.{m:02d}.2020"
              for m in (1, 2, 3, 4) for d in range(1, 11)]
    return "\n".join(linjer) + "\nVedtaksdato: 28.05.2026\n"


def test_dokumentdatoen_regnes_av_HELE_lista():
    """Med maks=30 fikk modellen «ingen dokumentdato» mens profilen
    meldte 28.05.2026 — og prompten sier «besvares med NØYAKTIG denne
    datoen», eller «si at det ikke står i dokumentet» hvis den mangler."""
    tekst = _mange_datoer_med_vedtak_bakerst()
    hele = finn_dokumentdato(sett_dato_roller(klassifiser_datoer(tekst)))
    assert hele["dato"] == "28.05.2026"
    assert hele["type"] == "vedtaksdato"

    avkortet = finn_dokumentdato(
        sett_dato_roller(klassifiser_datoer(tekst, maks=30)))
    assert avkortet["dato"] is None, "forutsetningen for testen holder ikke"


def test_svarveien_bruker_hele_lista():
    """Vakt mot at grensen sniker seg tilbake inn i datovalget."""
    import inspect

    import dokument_api
    kilde = inspect.getsource(dokument_api.svar_paa_sporsmal)
    assert "klassifiser_datoer(raa_tekst, maks=" not in kilde
    assert "MAKS_DATOER_I_PROMPT" in kilde


# ------------------------------------------------------------------ #
#  F2.2 — strekkodeskanningen må ikke miste koder                      #
# ------------------------------------------------------------------ #

def test_vektortegnede_strekkoder_finnes_fortsatt():
    """Revisjonen foreslo å hoppe over sider uten innebygde bilder.
    Målt mot den ekte testbunken ville det mistet BEGGE kodene: de står
    på side 3 og 10, og begge sidene har null innebygde bilder — kodene
    er VEKTORTEGNET. Å senke oppløsningen er heller ikke trygt (1.5x
    fant begge, 1.0x fant ingen).

    Denne testen vokter at innsnevringen som faktisk ble gjort — hopp
    over sider uten bilder OG uten tegninger — ikke mister noe."""
    import os

    import dokument_api
    pdf = os.path.join(dokument_api.ROT, "data", "korpus",
                       "syntetisk_bunke_tekstlag.pdf")
    if not os.path.exists(pdf):
        pytest.skip("korpusfila er ikke på denne maskinen")
    koder = dokument_api.les_strekkoder_bytes(open(pdf, "rb").read())
    assert {k["side"] for k in koder} == {3, 10}
    assert all(k["type"] == "CODE128" for k in koder)
