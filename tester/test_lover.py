"""
Tester for lovoppslaget (R76): to folketrygdlover som bruker de SAMME
paragrafnumrene om ULIKE ting.

«§ 8-1» er uførepensjon i 1966-loven og sykepenger i 1997-loven. 18 av
kapitlene betyr noe annet i den ene enn i den andre. Slår vi opp i feil
lov, får vi et svar som ser helt riktig ut — og et svar som ser riktig
ut, men er hentet fra en opphevet lov, er verre enn ingen svar.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")

from delt import lover as L

# Lovtekstene ligger i data/ (for store for git). Er de ikke hentet på
# denne maskinen, hopper vi over de testene som trenger selve teksten —
# i stedet for å feile på noe som ikke er en kodefeil.
def _tekst_finnes(lov_id):
    try:
        return os.path.exists(os.path.join(L.ROT, L.lov(lov_id)["fil"]))
    except Exception:
        return False


trenger_tekst = pytest.mark.skipif(
    not (_tekst_finnes("ftrl-1997") and _tekst_finnes("ftrl-1966")),
    reason="lovtekstene er ikke hentet — kjør skript/hent_lovtekst.py")


# ------------------------------------------------------------------ #
#  Registeret                                                          #
# ------------------------------------------------------------------ #

def test_begge_lovene_er_registrert():
    alle = L.lover()
    assert "ftrl-1997" in alle
    assert "ftrl-1966" in alle


def test_registeret_sier_hvilken_som_gjelder():
    """En opphevet lov skal aldri kunne forveksles med gjeldende rett."""
    assert L.lov("ftrl-1997")["status"] == "gjeldende"
    assert L.lov("ftrl-1966")["status"] == "opphevet"


def test_ukjent_lov_navngir_alternativene():
    with pytest.raises(KeyError) as feil:
        L.lov("ftrl-2099")
    assert "ftrl-1997" in str(feil.value)


@pytest.mark.parametrize("felt", ["tittel", "lovdata_id", "status",
                                  "gjelder_fra", "kilde", "fil"])
@pytest.mark.parametrize("lov_id", ["ftrl-1997", "ftrl-1966"])
def test_alle_paakrevde_felt_star_i_registeret(lov_id, felt):
    assert L.lov(lov_id).get(felt)


# ------------------------------------------------------------------ #
#  Kapitlene — det er de som navngir ytelsene                          #
# ------------------------------------------------------------------ #

@trenger_tekst
@pytest.mark.parametrize("kapittel,forventet", [
    ("4", "Dagpenger"), ("8", "Sykepenger"),
    ("11", "Arbeidsavklaringspenger"), ("12", "Uføretrygd"),
])
def test_kapitlene_i_gjeldende_lov(kapittel, forventet):
    assert forventet in L.kapitler("ftrl-1997")[kapittel]


@trenger_tekst
def test_kapittelnummeret_klippes_ikke_av_et_ord():
    """«Kap. 4 Dagpenger» (uten punktum etter tallet) ga kapittelnummer
    «4 D», fordi bokstaven etter tallet ble tatt for en kapittelbokstav."""
    assert L.kapitler("ftrl-1966")["4"].startswith("Dagpenger")


@trenger_tekst
def test_kapittelbokstav_beholdes_naar_den_er_ekte():
    assert "11 A" in L.kapitler("ftrl-1997")


@trenger_tekst
def test_de_to_lovene_bruker_samme_nummer_om_ulike_ting():
    """Selve grunnen til at lovene må holdes fra hverandre."""
    gammel, ny = L.kapitler("ftrl-1966"), L.kapitler("ftrl-1997")
    assert "Uførepensjon" in gammel["8"]
    assert "Sykepenger" in ny["8"]
    ulike = [k for k in set(gammel) & set(ny)
             if gammel[k][:10].lower() != ny[k][:10].lower()]
    assert len(ulike) >= 15, f"forventet mange avvik, fant {len(ulike)}"


# ------------------------------------------------------------------ #
#  Oppslag                                                             #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("inn,ut", [
    ("§ 8-1", "§ 8-1"), ("§8-1", "§ 8-1"), ("8-1", "§ 8-1"),
    ("paragraf 8-1", "§ 8-1"), ("§ 8 - 1", "§ 8-1"),
])
def test_referansen_normaliseres(inn, ut):
    assert L.normaliser(inn) == ut


@trenger_tekst
def test_oppslag_i_oppgitt_lov_gir_teksten():
    svar = L.slaa_opp("§ 8-1", "ftrl-1997")
    assert svar["funnet"] is True
    assert svar["kapittel"] == "8"
    assert svar["kapittel_tittel"] == "Sykepenger"
    assert "sykepenger" in svar["tekst"].lower()


@trenger_tekst
def test_samme_referanse_i_den_andre_loven_gir_noe_HELT_annet():
    svar = L.slaa_opp("§ 8-1", "ftrl-1966")
    assert svar["funnet"] is True
    assert "Uførepensjon" in svar["kapittel_tittel"]


@trenger_tekst
def test_paragraf_som_ikke_finnes_gir_ikke_naermeste_nabo():
    svar = L.slaa_opp("§ 99-99", "ftrl-1997")
    assert svar["funnet"] is False
    assert svar["tekst"] is None


# ------------------------------------------------------------------ #
#  Flertydighet — kjernen                                              #
# ------------------------------------------------------------------ #

@trenger_tekst
def test_referanse_uten_lov_er_flertydig_og_gjetter_ikke():
    svar = L.tolk_referanse("§ 8-1")
    assert svar["flertydig"] is True
    assert svar["valgt_lov"] is None
    assert "Sykepenger" in svar["begrunnelse"]
    assert "Uførepensjon" in svar["begrunnelse"]


@trenger_tekst
def test_oppgitt_lov_fjerner_flertydigheten():
    svar = L.tolk_referanse("§ 8-1", lov_id="ftrl-1966")
    assert svar["flertydig"] is False
    assert svar["valgt_lov"] == "ftrl-1966"


@trenger_tekst
def test_dokumentdatoen_avgjor_lovvalget():
    ny = L.tolk_referanse("§ 8-1", dokumentdato="2026-05-08")
    assert ny["valgt_lov"] == "ftrl-1997"
    gammel = L.tolk_referanse("§ 8-1", dokumentdato="1990-03-01")
    assert gammel["valgt_lov"] == "ftrl-1966"


def test_ukjent_dato_gir_ikke_et_lovvalg():
    """Et vedtak vi ikke kan tidfeste, kan ikke knyttes til en bestemt
    lov uten å gjette — og en gjetning om hjemmelen er verre enn ingen."""
    svar = L.lov_for_dato(None)
    assert svar["lov"] is None
    assert "ukjent" in svar["begrunnelse"].lower()


def test_uleselig_dato_sies_ifra_om():
    svar = L.lov_for_dato("i fjor en gang")
    assert svar["lov"] is None
    assert "lese" in svar["begrunnelse"].lower()


@trenger_tekst
def test_dato_paa_skillet_velger_den_nye_loven():
    """1997-loven gjelder FRA 1. mai 1997 — den datoen hører til den nye."""
    assert L.lov_for_dato("1997-05-01")["lov"] == "ftrl-1997"
    assert L.lov_for_dato("1997-04-30")["lov"] == "ftrl-1966"


# ------------------------------------------------------------------ #
#  Ytelsessøk på tvers av lovene                                       #
# ------------------------------------------------------------------ #

@trenger_tekst
def test_ytelsessok_finner_bade_gammel_og_ny_hjemmel():
    """Et gammelt vedtak om «uførepensjon» hører til 1966-lovens
    kapittel 8; dagens «uføretrygd» står i 1997-lovens kapittel 12.
    Søker man bare i gjeldende lov, finner man ikke det gamle."""
    treff = L.sok_ytelse("uføre")
    par = {(t["lov"], t["kapittel"]) for t in treff}
    assert ("ftrl-1997", "12") in par
    assert ("ftrl-1966", "8") in par


@trenger_tekst
def test_gjeldende_rett_kommer_forst():
    assert L.sok_ytelse("sykepeng")[0]["status"] == "gjeldende"


@trenger_tekst
def test_ytelsessok_kan_avgrenses_til_en_lov():
    treff = L.sok_ytelse("sykepeng", lov_id="ftrl-1997")
    assert {t["lov"] for t in treff} == {"ftrl-1997"}


def test_tomt_sok_gir_ingen_treff():
    assert L.sok_ytelse("") == []
    assert L.sok_ytelse(None) == []


@trenger_tekst
@pytest.mark.parametrize("navn,lov,kapittel", [
    ("attforingspenger", "ftrl-1966", "5B"),
    ("rehabiliteringspenger", "ftrl-1966", "5A"),
])
def test_stammen_finner_kapitlet_naar_endelsen_er_en_annen(navn, lov, kapittel):
    """Kapitlene navngir ikke alltid ytelsen med samme endelse:
    «attføringspenger» står i «Ytelser under yrkesrettet attføring».
    Fugebokstaven «s» hører til sammensetningen, ikke til stammen."""
    treff = L.sok_ytelse(navn)
    assert (treff[0]["lov"], treff[0]["kapittel"]) == (lov, kapittel)


@trenger_tekst
def test_sok_taaler_alle_tre_skrivemaatene_av_aeoeaa():
    """Ytelseslista er skrevet uten særtegn, kapitlene med. Uten
    normalisering fant «uforetrygd» aldri kapitlet «Uføretrygd»."""
    for skrivemaate in ("uføretrygd", "uforetrygd", "ufoeretrygd"):
        treff = L.sok_ytelse(skrivemaate, lov_id="ftrl-1997")
        assert treff and treff[0]["kapittel"] == "12", skrivemaate


# ------------------------------------------------------------------ #
#  Hjemmel etter dokumentets alder — begge lovene i bruk               #
# ------------------------------------------------------------------ #

def _profil(tekst):
    from delt.dokumentprofil import bygg_profil
    from delt.tekstuttrekk import (finn_dokumentdato, klassifiser_datoer,
                                   sett_dato_roller, strukturert_uttrekk)
    datoer = sett_dato_roller(klassifiser_datoer(tekst))
    return bygg_profil(tekst, datoer_detaljert=datoer,
                       dokumentdato=finn_dokumentdato(datoer),
                       struktur=strukturert_uttrekk(tekst))


@trenger_tekst
@pytest.mark.parametrize("tekst,lov,status", [
    ("Vedtak om uførepensjon\nVedtaksdato: 12.03.1994", "ftrl-1966",
     "opphevet"),
    ("Vedtak om uføretrygd\nVedtaksdato: 12.03.2026", "ftrl-1997",
     "gjeldende"),
])
def test_hjemmelen_folger_dokumentets_alder(tekst, lov, status):
    """Et vedtak fra 1994 skal leses mot loven som gjaldt DA — ikke mot
    dagens. Den gamle loven er hjemmelen for vedtak som fortsatt har
    virkning."""
    hjemmel = _profil(tekst)["hjemmel"]
    assert hjemmel["lov"] == lov
    assert hjemmel["status"] == status


@trenger_tekst
def test_samme_ytelse_gir_ULIKT_kapittel_i_de_to_lovene():
    """Kjernen i hele oppsettet: «sykepenger» er kapittel 3 i den gamle
    loven og kapittel 8 i den nye. Uten å velge lov etter dokumentets
    alder ville det ene svaret vært feil — og sett riktig ut."""
    gammel = _profil("Vedtak om sykepenger\nVedtaksdato: 12.03.1994")
    ny = _profil("Vedtak om sykepenger\nVedtaksdato: 12.03.2026")
    assert gammel["hjemmel"]["ytelse_kapittel"] == "3"
    assert ny["hjemmel"]["ytelse_kapittel"] == "8"


@trenger_tekst
def test_hjemmel_uten_dokumentdato_velger_ikke_lov():
    hjemmel = _profil("Vedtak om sykepenger uten dato.")["hjemmel"]
    assert hjemmel["lov"] is None
    assert "ukjent" in hjemmel["begrunnelse"].lower()


@trenger_tekst
def test_hvert_dokument_i_en_bunke_far_sin_egen_lov():
    """En arkivbunke kan spenne over lovskiftet i 1997. Da har
    dokumentene i den ULIK hjemmel, og én lov for hele filen ville vært
    feil for halvparten."""
    bunke = ("[Side 1 av 2]\nVedtak om uførepensjon\nVedtaksdato: 12.03.1994\n"
             "[Side 2 av 2]\nVedtak om uføretrygd\nVedtaksdato: 12.03.2026\n")
    dokumenter = _profil(bunke)["dokumenter"]
    assert len(dokumenter) == 2
    assert [d["lov"] for d in dokumenter] == ["ftrl-1966", "ftrl-1997"]
    assert [d["lov_status"] for d in dokumenter] == ["opphevet", "gjeldende"]
