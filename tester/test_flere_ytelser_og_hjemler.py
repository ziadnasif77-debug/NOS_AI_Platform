"""
Tester for `ytelser[]` og `hjemler[]` — flere ytelser og flere
lovhenvisninger per dokument (R94/R95).

Fellesnevneren: ETT felt tapte informasjon uten å si fra. `ytelse.navn`
ga bare det lengste treffet, så et AAP-vedtak som også nevnte
sykepengeperioden rapporterte én ytelse. `hjemmel` sa hvilken lov som
gjaldt, men ikke HVA dokumentet viste til — og et vedtak viser gjerne
til flere paragrafer.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api
from delt.tekstuttrekk import (finn_alle_ytelser, finn_lovhenvisninger,
                               finn_ytelse)

AAP_VEDTAK = """Vedtak om arbeidsavklaringspenger
Vedtaksdato: 17.05.2024
Du har mottatt sykepenger fram til 30.04.2024.
Vedtaket er fattet etter folketrygdloven § 11-5, jf. kapittel 8.
Klagefrist etter forvaltningsloven § 29.
"""


def _profil(tekst=AAP_VEDTAK):
    return api.DokumentKontekst(tekst, antall_sider=1).profil


# ------------------------------------------------------------------ #
#  1. Flere ytelser                                                    #
# ------------------------------------------------------------------ #

def test_begge_ytelsene_kommer_med():
    """Kjernen: et AAP-vedtak viser nesten alltid til sykepengeperioden
    som tok slutt. Med ett felt forsvant den.

    Begge står med NAVs offisielle temakode (R127) — det er den formen
    en robot ruter på — OG med sin egen betegnelse (R134), som er den
    et menneske ruter på når to ytelser deler tema."""
    assert _profil()["ytelser"] == [
        {"navn": {"kode": "AAP", "term": "Arbeidsavklaringspenger"},
         "betegnelse": "Arbeidsavklaringspenger"},
        {"navn": {"kode": "SYK", "term": "Sykepenger"},
         "betegnelse": "Sykepenger"},
    ]


def test_rekkefolgen_er_forste_forekomst_ikke_lengde():
    tekst = "Saken gjelder sykepenger og senere arbeidsavklaringspenger."
    assert finn_alle_ytelser(tekst) == ["sykepenger",
                                        "arbeidsavklaringspenger"]


def test_entallsfeltet_ligger_alltid_i_lista():
    """Et speil med samme krav som de øvrige: sier de to feltene ulike
    ting, er dupliseringen blitt en motsigelse.

    HELE oppføringen sammenlignes, ikke bare koden: temakodene er
    mange-til-én (uføretrygd og uførepensjon er begge UFO), så en
    kodesammenligning ville godtatt at entallsfeltet og lista pekte på
    ulike ytelser. Etter R134 holder det ikke å sammenligne `navn`
    heller — pleiepenger og omsorgspenger har IDENTISK `navn`, og bare
    `betegnelse` skiller dem."""
    profil = _profil()
    assert {"navn": profil["ytelse"]["navn"],
            "betegnelse": profil["ytelse"]["betegnelse"]} in profil["ytelser"]


def test_entallsfeltet_er_den_mest_spesifikke_ikke_den_forste():
    """Dokumentert med vilje: `ytelse.navn` er LENGSTE treff (det mest
    spesifikke navnet), `ytelser[0]` er det som står først. Sammenfaller
    de ikke, er begge riktige — de svarer på ulike spørsmål."""
    tekst = "Saken gjelder sykepenger og senere arbeidsavklaringspenger."
    assert finn_ytelse(tekst) == "arbeidsavklaringspenger"
    assert finn_alle_ytelser(tekst)[0] == "sykepenger"


def test_uten_ytelse_er_lista_tom_ikke_null():
    assert _profil("Et brev uten ytelser.\nDatert 01.03.2024")["ytelser"] == []


def test_samme_ytelse_nevnt_flere_ganger_er_en_oppforing():
    assert finn_alle_ytelser("dagpenger dagpenger dagpenger") == ["dagpenger"]


def test_aeoa_leses_uansett_skrivemate():
    """Lista er skrevet uten særtegn, dokumentene skriver «uføretrygd».
    Uten normaliseringen falt fire av de viktigste ytelsene stille bort."""
    for skrivemate in ("uføretrygd", "uforetrygd", "ufoeretrygd"):
        assert "uforetrygd" in finn_alle_ytelser(f"Vedtak om {skrivemate}.")


# ------------------------------------------------------------------ #
#  2. Lovhenvisninger                                                  #
# ------------------------------------------------------------------ #

def test_bade_paragraf_og_kapittel_fanges():
    refs = [h["referanse"] for h in _profil()["hjemler"]]
    assert "§ 11-5" in refs
    assert "kapittel 8" in refs


def test_delt_paragraf_leses_ikke_som_udelt():
    """«§ 8-2» må ikke bli «§ 8» med leddet tapt i stillhet."""
    refs = [h["referanse"] for h in finn_lovhenvisninger("etter § 8-2 i loven")]
    assert refs == ["§ 8-2"]


def test_samme_paragraf_nevnt_fem_ganger_er_en_henvisning():
    tekst = "§ 8-2 … § 8-2 … § 8-2"
    assert len(finn_lovhenvisninger(tekst)) == 1


def test_lovnavn_rett_foran_registreres():
    funn = finn_lovhenvisninger("etter folketrygdloven § 11-5")
    assert funn[0]["lov_nevnt"] is True
    assert finn_lovhenvisninger("jf. § 11-5")[0]["lov_nevnt"] is False


# ------------------------------------------------------------------ #
#  3. Oppslaget følger DOKUMENTETS alder (R77)                         #
# ------------------------------------------------------------------ #

def test_samme_kapittelnummer_betyr_ulike_ting_i_de_to_lovene():
    """Hele grunnen til at begge lovene ligger i registeret. «Kapittel 8»
    er sykepenger i 1997-loven og uførepensjon i 1966-loven — leses et
    1994-vedtak mot dagens lov, blir svaret feil på en måte som ser helt
    riktig ut."""
    ny = {h["referanse"]: h for h in _profil()["hjemler"]}
    gammel = {h["referanse"]: h
              for h in _profil(AAP_VEDTAK.replace("17.05.2024",
                                                  "17.05.1994"))["hjemler"]}
    assert ny["kapittel 8"]["lov"] == "ftrl-1997"
    assert gammel["kapittel 8"]["lov"] == "ftrl-1966"
    assert (ny["kapittel 8"]["kapittel_tittel"]
            != gammel["kapittel 8"]["kapittel_tittel"])


def test_kapitteltittelen_slas_faktisk_opp():
    """Sto null i første utgave fordi `kapitler()` gir {nummer: tittel},
    ikke {nummer: {tittel: …}} — en stille feil, for null er en lovlig
    verdi her."""
    ny = {h["referanse"]: h for h in _profil()["hjemler"]}
    assert ny["kapittel 8"]["kapittel_tittel"] == "Sykepenger"
    assert ny["§ 11-5"]["kapittel_tittel"] == "Arbeidsavklaringspenger"


def test_uten_dokumentdato_er_henvisningen_flertydig():
    """Å velge én av to lover uten grunnlag ville gitt et svar som ser
    riktig ut. Da sier vi heller at vi ikke vet."""
    profil = _profil("Vedtaket er fattet etter § 8-2.")
    assert profil["dokument"]["dato"] is None
    for h in profil["hjemler"]:
        assert h["flertydig"] is True
        assert h["lov"] is None


def test_udelt_paragraf_tilskrives_ikke_folketrygdloven():
    """Folketrygdloven nummererer kapittel-ledd (§ 8-2). En UDELT
    paragraf hører derfor til en annen lov — oftest forvaltningsloven.
    Å skrive «ftrl-1997» på den ville vært en påstand vi VET er feil."""
    treff = [h for h in _profil()["hjemler"] if h["referanse"] == "§ 29"]
    assert len(treff) == 1
    assert treff[0]["lov"] is None
    assert treff[0]["kapittel"] is None
    assert "ANNEN lov" in treff[0]["merknad"]


def test_uten_henvisninger_er_lista_tom():
    assert _profil("Et brev uten lovhenvisninger.\n"
                   "Dokumentdato: 01.03.2024")["hjemler"] == []


# ------------------------------------------------------------------ #
#  4. «hjemmel» og «hjemler» svarer på ULIKE spørsmål                  #
# ------------------------------------------------------------------ #

def test_hjemmel_finnes_selv_uten_en_eneste_henvisning():
    """`hjemmel` sier hvilken lov som GJALDT. Den er satt av datoen
    alene, og skal ikke forsvinne fordi dokumentet ikke siterer noe."""
    profil = _profil("Dokumentdato: 01.03.2024\nEt brev uten paragrafer.")
    assert profil["gjeldende_lov"]["lov"] == "ftrl-1997"
    assert profil["hjemler"] == []
