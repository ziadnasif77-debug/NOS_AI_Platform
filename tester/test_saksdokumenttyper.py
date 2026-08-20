"""
R241: saksbehandlingens egne dokumenttyper.

Kodeverket kjente 17 typer, og alle beskrev dokumenter som kommer INN i
en sak — søknad, legeerklæring, faktura, meldekort. Ingen av dem
beskrev sakens egen gang: journalnotatet, telefonnotatet, purringen,
dokumentasjonskravet, klagevedtaket.

Målt før utvidelsen, på tolv realistiske saksdokumenter: 12 av 12
klassifisert feil. Ni endte som «ingen type», og tre var AKTIVT feil:

    «Telefonsamtalenotat … manglende meldekort»  → meldekort
    «Klagevedtak … har behandlet klagen din»     → klage
    «Vedtak i klagesak»                          → vedtak

De to siste er den dyre feilen. Et klagevedtak er svaret PÅ en klage.
Når begge bærer koden «klage», kan ingen sammenligne førstevedtak mot
klagevedtak — og det er nettopp spørsmålet en saksmappe finnes for å
svare på: hva ble bestemt, ble det klaget, og hva ble bestemt til slutt.

Testene her vokter tre ting: at de nye typene kjennes igjen, at de gamle
står helt uendret, og at kodeverket henger sammen på tvers av de fire
filene som må enes om det.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

from delt.tekstuttrekk import (DOKUMENTTYPE_TERM, dokumenttype_i_tittel,
                               gjett_dokumenttype)

# De elleve nye typene R241 innførte.
NYE = ("klagevedtak", "journalnotat", "telefonnotat", "oppfolgingsnotat",
       "internvurdering", "dokumentasjonskrav", "purring",
       "veiledningsbrev", "arbeidsgiveropplysninger", "legeopplysninger",
       "referat")


# ------------------------------------------------------------------ #
#  De nye typene kjennes igjen                                        #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("forventet,tekst", [
    ("journalnotat",
     "Journalnotat\nSaksnummer: 4417820\nBruker ringte om status i saken."),
    ("telefonnotat",
     "Telefonsamtalenotat\nSamtale med bruker om manglende meldekort."),
    ("klagevedtak",
     "Klagevedtak\nNAV Klageinstans har behandlet klagen din av 03.02.2026."),
    ("klagevedtak", "Vedtak i klagesak\nKlagen tas til følge."),
    ("klagevedtak", "Klageavgjørelse\nVedtaket opprettholdes."),
    ("dokumentasjonskrav",
     "Dokumentasjonskrav\nVi trenger flere opplysninger før vi kan "
     "behandle søknaden."),
    ("purring", "Purring\nVi har ikke mottatt dokumentasjonen vi ba om."),
    ("veiledningsbrev",
     "Veiledningsbrev\nHer er informasjon om rettighetene dine."),
    ("internvurdering",
     "Intern vurdering\nSaksbehandlers faglige vurdering av vilkårene."),
    ("oppfolgingsnotat",
     "Oppfølgingsnotat\nOppfølgingssamtale gjennomført 15.04.2026."),
    ("arbeidsgiveropplysninger",
     "Arbeidsgiveropplysninger\nOpplysninger fra arbeidsgiver om "
     "ansettelsesforholdet."),
    ("legeopplysninger",
     "Legeopplysninger\nOpplysninger fra behandlende lege om "
     "funksjonsnivået."),
    ("referat", "Referat\nMøtereferat fra dialogmøte 20.05.2026."),
])
def test_saksdokument_kjennes_igjen(forventet, tekst):
    assert gjett_dokumenttype(tekst) == forventet


def test_ocr_skriver_oe_for_o_slash():
    """OCR gjengir jevnlig ø som «oe». Et mønster som bare tåler ø og o
    ville sett «Oppfoelgingsnotat» som ukjent — og OCR er nettopp der
    disse dokumentene kommer fra."""
    assert gjett_dokumenttype(
        "Oppfoelgingsnotat\nOppfoelgingssamtale gjennomfoert.") \
        == "oppfolgingsnotat"
    assert gjett_dokumenttype(
        "Klageavgjoerelse\nVedtaket opprettholdes.") == "klagevedtak"


# ------------------------------------------------------------------ #
#  Kjernen: klage og klagevedtak er IKKE samme dokument               #
# ------------------------------------------------------------------ #

def test_klage_og_klagevedtak_skilles():
    """Uten dette skillet kan ingen sammenligne førstevedtak mot
    klagevedtak — spørsmålet en saksmappe finnes for å svare på."""
    klage = "Klage på vedtak om sykepenger\nJeg klager på vedtaket av 01.02."
    klagevedtak = ("Klagevedtak\nNAV Klageinstans har behandlet klagen "
                   "din og omgjør vedtaket.")
    assert gjett_dokumenttype(klage) == "klage"
    assert gjett_dokumenttype(klagevedtak) == "klagevedtak"
    assert gjett_dokumenttype(klage) != gjett_dokumenttype(klagevedtak)


def test_klagevedtak_er_ikke_et_vanlig_vedtak():
    """«Vedtak i klagesak» begynner med ordet «vedtak». Uavgjort på
    posisjon avgjøres av lengste treff, og det MÅ være klagevedtaket —
    ellers blir andregangsvedtaket talt som et førstegangsvedtak."""
    assert dokumenttype_i_tittel("Vedtak i klagesak") == "klagevedtak"
    assert dokumenttype_i_tittel("Vedtak om sykepenger") == "vedtak"


def test_telefonnotat_stjeles_ikke_av_det_det_handler_om():
    """Et notat om et manglende meldekort er et NOTAT. Før R241 vant
    brødtekstordet «meldekort» fordi tittelen ikke sa noe kjent."""
    assert gjett_dokumenttype(
        "Telefonsamtalenotat\nBruker ringte om meldekort. Meldekort "
        "for uke 12 og 13 mangler fortsatt.") == "telefonnotat"


# ------------------------------------------------------------------ #
#  Motprøven: de gamle typene står uendret                            #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("forventet,tekst", [
    ("klage", "Klage på vedtak om sykepenger\nJeg klager på vedtaket."),
    ("vedtak", "Vedtak om sykepenger\nDu får innvilget sykepenger."),
    ("soknad", "Søknad om dagpenger\nJeg søker om dagpenger."),
    ("faktura", "Faktura\nForfallsdato: 24.06.2026\nKID: 123"),
    ("legeerklaring", "Legeerklæring\nPasienten er sykmeldt."),
    ("inntektsmelding", "Inntektsmelding\nArbeidsgiver melder inntekt."),
    ("sykmelding", "Sykmelding\nSykmeldt fra 01.03."),
    ("meldekort", "Meldekort\nUke 12 og 13."),
    ("egenerklaring", "Egenerklæring\nJeg bekrefter opplysningene."),
    ("returslipp", "Returslipp\nDokumentkontroll av bunken."),
    ("kontoutskrift", "Kontoutskrift\nAvtaleGiro og innbetalinger."),
    ("attest", "Attest\nBekreftelse på arbeidsforhold."),
    ("kvittering", "Kvittering\nBetaling mottatt."),
    ("brev", "Til deg som søker\nMed vennlig hilsen NAV"),
])
def test_gamle_typer_er_uendret(forventet, tekst):
    assert gjett_dokumenttype(tekst) == forventet


def test_legeopplysninger_stjeler_ikke_legeerklaringen():
    """To ulike dokumenter fra samme avsender. Blandes de, mister
    forventningsrapporten for legeerklæring sitt grunnlag."""
    assert gjett_dokumenttype("Legeerklæring\nPasienten er sykmeldt.") \
        == "legeerklaring"
    assert gjett_dokumenttype("Legeopplysninger\nOpplysninger fra lege.") \
        == "legeopplysninger"


# ------------------------------------------------------------------ #
#  Kodeverket henger sammen på tvers av filene                        #
# ------------------------------------------------------------------ #

def test_alle_nye_typer_har_term():
    mangler = [t for t in NYE if t not in DOKUMENTTYPE_TERM]
    assert not mangler, f"nye typer uten lesbar term: {mangler}"


def test_kodene_er_uten_aeoeaa():
    """Kodene matches mot og sammenlignes med OCR-tekst; termen bærer
    æøå, koden ikke. Samme regel som de sytten eldre kodene følger."""
    for kode in NYE:
        assert not (set("æøåÆØÅ") & set(kode)), f"koden «{kode}» har æøå"


def test_nye_typer_kan_spoerres_om_i_en_bunke():
    """Uten et spørsmålsord kan «Hva står i klagevedtaket?» ikke rutes
    til ett dokument i mappa — og svares da fra førstevedtaket."""
    from delt.dokumentruting import SPORSMAALSORD
    mangler = [t for t in NYE if t not in SPORSMAALSORD]
    assert not mangler, f"nye typer uten spørsmålsord: {mangler}"


def test_spoersmaal_om_klagevedtaket_treffer_bare_klagevedtaket():
    """Sammensatte ord er ikke dokumentet (modulens hovedregel):
    «klagevedtaket» skal ikke også trigge «vedtak» og «klage» — da ville
    spørsmålet nevne tre typer, og rutingen gir opp."""
    from delt.dokumentruting import typer_i_sporsmal
    assert typer_i_sporsmal("Hva står i klagevedtaket?") == ["klagevedtak"]


def test_regelfila_kjenner_de_nye_typene():
    """`regler/dokumenttype_forventninger.txt` lister de gyldige typene
    for brukeren. Står ikke en type der, kan ingen konfigurere den —
    linja ville blitt hoppet over i stillhet."""
    from delt.prompter import regelfil
    with open(regelfil("dokumenttype_forventninger.txt"),
              encoding="utf-8-sig") as fil:
        innhold = fil.read()
    mangler = [t for t in NYE if t not in innhold]
    assert not mangler, f"ikke nevnt i regelfila: {mangler}"


def test_nye_typer_har_ingen_forventninger_enda():
    """Med vilje: vi har ikke MÅLT hva et journalnotat alltid inneholder,
    og en uforankret forventning roper «mangler» på friske dokumenter
    (samme grunn som KID ikke står på faktura)."""
    from delt.typeforventninger import forventninger_for
    for kode in NYE:
        assert forventninger_for(kode) is None, (
            f"«{kode}» har fått forventninger uten at de er målt")
