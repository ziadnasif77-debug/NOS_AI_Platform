"""
Tester for saks-, økonomi- og arbeidsfeltene (R71) — og for de to
lesefeilene kartleggingen fant i adressene og dokumenttypen (R72/R73).

Gjennomgående krav: uttrekket skal kreve en EKSPLISITT etikett. Et tall
uten etikett blir aldri et vedtaksnummer, og et beløp uten etikett blir
aldri en dagsats. Det som ikke står merket, finnes ikke.
"""
import sys

import pytest

sys.path.insert(0, ".")

from delt.saksfelter import (arbeid_felter, finn_arbeidsgiver, finn_dagsats,
                             finn_dokumentnummer, finn_journalnummer,
                             finn_manedsbelop, finn_referanse,
                             finn_stilling, finn_stillingsprosent,
                             finn_tilbakebetaling, finn_utbetalt_belop,
                             finn_vedtaksnummer, okonomi_felter, sak_felter)
from delt.tekstuttrekk import finn_adresser, gjett_dokumenttype


# ------------------------------------------------------------------ #
#  Sak                                                                 #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("tekst,forventet", [
    ("Journalnummer: 2026001234", "2026001234"),
    ("Journalnr. 12/3456", "12/3456"),
    ("Journalpost 998877", "998877"),
    ("Jnr 445566", "445566"),
])
def test_journalnummer_i_sine_former(tekst, forventet):
    assert finn_journalnummer(tekst) == forventet


def test_vedtaksnummer_er_ikke_saksnummer():
    """Et vedtak kan være ett av flere i samme sak. Blandes de to, peker
    referansen på feil dokument."""
    tekst = "Saksnummer: 4417820\nVedtaksnummer: 55/9911"
    assert finn_vedtaksnummer(tekst) == "55/9911"


def test_dokumentnummer_og_referanse():
    assert finn_dokumentnummer("Dokumentnr. 998877") == "998877"
    assert finn_referanse("Vår referanse: ABC-123/26") == "ABC-123/26"
    assert finn_referanse("Deres ref: SAK-99") == "SAK-99"


def test_umerkede_tall_blir_ikke_saksfelter():
    """Kjernen: et tall i teksten er bare et tall."""
    felter = sak_felter("Vi viser til brevet ditt. 4417820 kroner er utbetalt.")
    assert all(v is None for v in felter.values()), felter


# ------------------------------------------------------------------ #
#  Økonomi                                                             #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("tekst", [
    "Dagsats: kr 1 234,00",
    "Dagsats 1 234,00",
    "Dagsatsen er kr 1 234,00",
    "Dagsatsen utgjør 1 234,00",
    "Sats per dag: 1 234,00",
])
def test_dagsats_i_skjemaform_og_setningsform(tekst):
    """Halvparten av NAV-dokumentene er skrevet i setninger, ikke i
    skjemafelt. Godtar vi bare «Dagsats: 1234», mister vi den andre
    halvparten."""
    assert finn_dagsats(tekst) == 1234.00, tekst


def test_manedsbelop_skilles_fra_dagsats():
    tekst = "Dagsats: kr 1 234,00\nMånedsbeløp: kr 24 680,00"
    okonomi = okonomi_felter(tekst)
    assert okonomi["dagsats"] == 1234.00
    assert okonomi["manedsbelop"] == 24680.00


def test_tilbakebetaling_forveksles_ikke_med_utbetaling():
    """Fortegnet på hele saken snur hvis disse blandes."""
    tekst = "Utbetalt: kr 1 000,00\nTilbakebetalingsbeløp: kr 250,00"
    okonomi = okonomi_felter(tekst)
    assert okonomi["utbetalt_belop"] == 1000.00
    assert okonomi["tilbakebetalingsbelop"] == 250.00


def test_belop_uten_etikett_blir_ikke_dagsats():
    assert finn_dagsats("Du får 1 234,00 kroner.") is None
    assert finn_manedsbelop("Beløpet er 24 680,00") is None
    assert finn_tilbakebetaling("250,00 kroner") is None


# ------------------------------------------------------------------ #
#  Arbeid                                                              #
# ------------------------------------------------------------------ #

def test_arbeidsgiver_stopper_for_organisasjonsnummeret():
    assert finn_arbeidsgiver(
        "Arbeidsgiver: Rema 1000 AS, Org. nr. 923 609 016") == "Rema 1000 AS"


def test_feltetiketten_vinner_over_overskriften():
    """Fra en ekte inntektsmelding: ordet «arbeidsgiver» står både i
    overskriften «Inntektsmelding fra arbeidsgiver» og som feltnavn
    lenger nede. Uten en regel om at feltetiketten STARTER sin linje,
    ble arbeidsgiveren «Innsendt via Altinn 28.04.2026 kl. 09:14»."""
    tekst = ("Inntektsmelding fra arbeidsgiver\n"
             "Innsendt via Altinn 28.04.2026 kl. 09:14\n"
             "Arbeidsgiver\n"
             "Nordbygg Entreprenoer AS\n"
             "Organisasjonsnummer 889000007")
    assert finn_arbeidsgiver(tekst) == "Nordbygg Entreprenoer AS"


def test_prosentandel_blir_ikke_et_belop():
    """Fra det samme dokumentet: «du får utbetalt 100 prosent av dette»
    ga utbetalt_belop = 100. En andel og en sum er ikke samme slags
    tall — 100 kroner er ikke 100 prosent."""
    assert finn_utbetalt_belop(
        "Sykepengegrunnlaget er kr 512 400 per aar, og du faar utbetalt "
        "100 prosent av dette.") is None


def test_ekte_belop_finnes_selv_naar_en_prosent_star_foran():
    assert finn_utbetalt_belop(
        "du faar utbetalt 100 prosent. Utbetalt beloep: kr 74 040,00") \
        == 74040.00


def test_stilling_forveksles_ikke_med_stillingsprosent():
    """«stilling» står inne i «Stillingsprosent». Uten en ordgrense ble
    stillingstittelen «sprosent: 80 %»."""
    assert finn_stilling("Stillingsprosent: 80 %") is None
    assert finn_stilling("Stilling: Butikkmedarbeider\n"
                         "Stillingsprosent: 80 %") == "Butikkmedarbeider"


@pytest.mark.parametrize("tekst,forventet", [
    ("Stillingsprosent: 80 %", 80),
    ("Stillingsandel 60", 60),
    ("Han har 50 % stilling", 50),
    ("Stillingsprosent: 100", 100),
])
def test_stillingsprosent_i_sine_former(tekst, forventet):
    assert finn_stillingsprosent(tekst) == forventet


def test_umulig_stillingsprosent_avvises():
    assert finn_stillingsprosent("Stillingsprosent: 250") is None
    assert finn_stillingsprosent("Stillingsprosent: 0") is None


def test_arsinntekt_og_manedslonn_holdes_fra_hverandre():
    """Slås de sammen, blir en årslønn og en månedslønn samme tall."""
    felter = arbeid_felter("Årsinntekt: 480 000,00\nMånedslønn: 40 000,00")
    assert felter["arsinntekt"] == 480000.00
    assert felter["manedslonn"] == 40000.00


def test_arbeidsforholdets_datoer():
    felter = arbeid_felter("Ansatt fra: 01.03.2020\nSluttdato: 31.12.2025")
    assert felter["startdato"] == "2020-03-01"
    assert felter["sluttdato"] == "2025-12-31"


# ------------------------------------------------------------------ #
#  Æøå skrives på tre måter                                            #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("tekst", [
    "Månedsbeløp: 24 680,00",
    "Månedsbeløpet er 24 680,00",
    "Maanedsbeloepet 24 680,00",
])
def test_etikettene_taaler_bestemt_form(tekst):
    """Norsk bøyer: dokumentene skriver like gjerne «Månedsbeløpet er
    …» som «Månedsbeløp: …». Godtar vi bare den ubøyde formen, mister
    vi alt som er skrevet i setninger."""
    assert finn_manedsbelop(tekst) == 24680.00, tekst


def test_boyningen_apner_ikke_for_feil_treff():
    """Endelsene godtas, men ikke noe annet: «stilling» skal fortsatt
    ikke treffe inne i «Stillingsprosent»."""
    assert finn_stilling("Stillingsprosent: 80 %") is None


def test_etikettene_taaler_aa_og_oe_skrivemaaten():
    """Eldre systemer og OCR gir «Maanedsbeloep» der dokumentet sier
    «Månedsbeløp». Uten dette faller feltet stille bort på et dokument
    som ser helt normalt ut."""
    assert finn_manedsbelop("Maanedsbeloep: 24 680,00") == 24680.00
    assert finn_manedsbelop("Månedsbeløp: 24 680,00") == 24680.00
    assert finn_manedsbelop("Manedsbelop: 24 680,00") == 24680.00


# ------------------------------------------------------------------ #
#  R72: adresselesingen                                                #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("tekst", [
    "Adresse: Storgata 12, 0181 OSLO",
    "Storgata 12, 0181 OSLO",
    "Ola Nordmann\nStorgata 12\n0181 OSLO",
])
def test_gateadressen_leses_i_sine_former(tekst):
    adresser = finn_adresser(tekst)
    assert adresser == [{"gate": "Storgata 12", "postnummer": "0181",
                         "poststed": "OSLO"}], tekst


def test_firmanavn_med_tall_blir_ikke_en_adresse():
    """«Rema 1000 AS» ble lest som postnummer 1000 i poststedet AS."""
    assert finn_adresser("Arbeidsgiver: Rema 1000 AS, Org. nr. 923 609 016") == []


def test_merket_felt_over_postnummeret_blir_ikke_gateadresse():
    """Linja over postnummeret er ikke automatisk en gate. Uten en
    formsjekk ble «Fnr: …» gateadressen til mottakeren."""
    adresser = finn_adresser("Fnr: 12345678910\n0181 OSLO")
    assert adresser == [{"gate": None, "postnummer": "0181",
                         "poststed": "OSLO"}]


def test_postboks_er_en_gyldig_adresse():
    assert finn_adresser("Postboks 123\n0181 OSLO")[0]["gate"] == "Postboks 123"


# ------------------------------------------------------------------ #
#  R73: dokumenttypen                                                  #
# ------------------------------------------------------------------ #

def test_tittelen_avgjor_dokumenttypen():
    """Et vedtaksbrev med beløp og forfallsdato ble klassifisert som
    FAKTURA: to svake treff i brødteksten slo ett sterkt i overskriften."""
    tekst = ("NAV Arbeid og ytelser\nVedtak om dagpenger\n"
             "Forfallsdato: 24.06.2026\nKID 1002345678911\n")
    assert gjett_dokumenttype(tekst) == "vedtak"


def test_faktura_er_fortsatt_faktura():
    assert gjett_dokumenttype(
        "Faktura nr 123\nForfallsdato: 24.06.2026\nKID 1002345678911") \
        == "faktura"


def test_klage_paa_et_vedtak_er_en_klage():
    """Rekkefølgen i tittelen avgjør: dokumentets egen art står først,
    og det den handler OM kommer etter. Telte vi forekomster, vant
    «vedtak» — en klage nevner vedtaket den klager på mange ganger."""
    tekst = ("Klage paa vedtak om arbeidsavklaringspengar\n"
             "Eg klagar paa vedtaket datert 08.05.2026.\n"
             "Vedtaket byggjer paa feil faktum. Vedtaket maa omgjerast.\n")
    assert gjett_dokumenttype(tekst) == "klage"


@pytest.mark.parametrize("tittel,forventet", [
    ("Legeerklaering ved arbeidsufoerhet", "legeerklaring"),
    ("Legeerklæring ved arbeidsuførhet", "legeerklaring"),
    ("Inntektsmelding fra arbeidsgiver", "inntektsmelding"),
    ("Sykmelding del D", "sykmelding"),
    ("Egenerklaering om sykefravaer", "egenerklaring"),
    ("Meldekort for uke 12", "meldekort"),
])
def test_sentrale_nav_dokumenttyper_kjennes_igjen(tittel, forventet):
    """Uten disse ble en legeerklæring stående som «vedtak», fordi ordet
    vedtak fantes et sted i teksten."""
    assert gjett_dokumenttype(tittel + "\nInnhold om vedtak og beløp.") \
        == forventet


def test_sidemarkoren_spiser_ikke_tittelplassen():
    """«[Side 1 av 10]» er kodegenerert og skal ikke telle som tittel."""
    assert gjett_dokumenttype(
        "[Side 1 av 2]\nVedtak om dagpenger\nForfallsdato: 24.06.2026") \
        == "vedtak"
