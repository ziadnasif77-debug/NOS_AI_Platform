"""
Tester for skillet mellom DOKUMENTETS EGEN DATO og datoene i innholdet.

Bakgrunnen: spør man «når er dette brevet fra?», er svaret dokumentets
egen dato — ikke fristen, perioden eller fødselsdatoen som tilfeldigvis
står nærmest. Uten dette skillet plukket systemet den første og beste
datoen. Reglene her er DETERMINISTISKE (ingen modell), så de kan testes
eksakt:

  1) bare datoer med rolle «dokument» kan bli dokumentdato
  2) sterkest bevis vinner: etikett > posisjon > PDF-metadata
  3) finnes ingen slik dato, sies det ærlig (None) — aldri en gjetning
  4) PDF-metadata på et SKANNET dokument er skannedatoen, og merkes sånn
"""
import sys
from datetime import date

import pytest

sys.path.insert(0, ".")

from delt.tekstuttrekk import (ROLLE_BEHANDLING, ROLLE_DOKUMENT,
                               ROLLE_INNHOLD, _ROLLE_TERM, _TYPE_TERM,
                               dokumentets_alder,
                               finn_dokumentdato, kodeverk,
                               klassifiser_datoer, rolle_for_type,
                               sett_dato_roller)


def _dokumentdato(tekst: str, ocr_brukt: bool = False) -> dict:
    return finn_dokumentdato(sett_dato_roller(klassifiser_datoer(tekst)),
                             ocr_brukt=ocr_brukt)


def _kandidat(dato, dtype, **ekstra):
    return {"dato": dato, "type": dtype, "begrunnelse": "test",
            "side": 1, **ekstra}


# ---------- roller ----------
def test_roller_skiller_dokument_fra_innhold():
    for dtype in ("vedtaksdato", "utstedt", "signaturdato", "dokumentdato",
                  "brevdato_sannsynlig", "pdf_opprettet"):
        assert rolle_for_type(dtype) == ROLLE_DOKUMENT, dtype
    for dtype in ("frist", "fodselsdato", "periode_start", "periode_slutt",
                  "utlop", "avreise"):
        assert rolle_for_type(dtype) == ROLLE_INNHOLD, dtype
    # mottatt/arkivert er om HÅNDTERINGEN — verken dokumentets dato
    # eller innhold, og skal aldri kuppe dokumentdatoen
    for dtype in ("mottatt", "arkivert"):
        assert rolle_for_type(dtype) == ROLLE_BEHANDLING, dtype


def test_ukjent_egendefinert_type_blir_innhold():
    """En ny etikett navngir nesten alltid noe dokumentet HANDLER OM.
    Å anta «dokument» ville latt en tilfeldig etikett kuppe datoen."""
    assert rolle_for_type("min_egen_type") == ROLLE_INNHOLD


# ---------- valg av dokumentdato ----------
def test_vedtaksbrev_velger_vedtaksdato_ikke_frist():
    """Selve regresjonen: fristen og perioden skal IKKE bli brevets dato."""
    resultat = _dokumentdato(
        "NAV Arbeid og ytelser\n"
        "Vedtaksdato: 12.06.2026\n\n"
        "Du har rett til dagpenger fra 01.07.2026 til 31.12.2026.\n"
        "Klagefrist: innen 05.07.2026.\n")
    assert resultat["dato"] == "2026-06-12"
    assert resultat["type"] == "vedtaksdato"
    assert resultat["konfidens"] == "hoy"


def test_dato_overst_paa_side_1_blir_brevdato():
    resultat = _dokumentdato(
        "15.03.2026\n\nTil Ola Nordmann\nUtbetaling skjer 20.04.2026.\n")
    assert resultat["dato"] == "2026-03-15"
    assert resultat["kilde"] == "posisjon"


def test_bare_innholdsdatoer_gir_aerlig_ingen():
    """Ingen dokumentdato er et GYLDIG svar — bedre enn en gjetning."""
    resultat = finn_dokumentdato([
        _kandidat("2026-07-05", "frist"),
        _kandidat("1985-04-03", "fodselsdato"),
        _kandidat("2026-07-01", "periode_start"),
    ])
    assert resultat["dato"] is None
    assert resultat["konfidens"] == "ingen"
    assert "innholdet" in resultat["begrunnelse"]


def test_etikett_slaar_pdf_metadata():
    resultat = finn_dokumentdato([
        _kandidat("2026-02-01", "pdf_opprettet", side=None),
        _kandidat("2026-06-12", "vedtaksdato"),
    ])
    assert resultat["dato"] == "2026-06-12"
    # den tapende kandidaten skal fortsatt være synlig, ikke forsvinne
    assert "2026-02-01" in [a["dato"] for a in resultat["alternativer"]]


def test_pdf_metadata_paa_skannet_dokument_merkes_som_skannedato():
    skannet = finn_dokumentdato(
        [_kandidat("2026-02-01", "pdf_opprettet", side=None)], ocr_brukt=True)
    assert skannet["dato"] == "2026-02-01"
    assert skannet["konfidens"] == "lav"
    assert "SKANNEDATOEN" in skannet["advarsel"]


def test_uenighet_mellom_like_sterke_kandidater_varsles():
    resultat = finn_dokumentdato([
        _kandidat("2026-06-12", "vedtaksdato"),
        _kandidat("2026-06-20", "utstedt"),
    ])
    assert resultat["dato"] == "2026-06-12"      # første vinner
    assert "ULIKE datoer" in resultat["advarsel"]
    assert "2026-06-20" in resultat["advarsel"]


def test_haandskrevet_dokumentdato_nedgraderes():
    resultat = finn_dokumentdato(
        [_kandidat("2026-06-12", "vedtaksdato", skrevet_for_hand=True)],
        ocr_brukt=True)
    assert resultat["konfidens"] == "middels"    # ned fra «hoy»
    assert "håndskrevet" in resultat["advarsel"]


def test_mottatt_dato_blir_ikke_dokumentdato():
    """«Mottatt 05.01.2026» sier når NAV fikk brevet — ikke når det ble
    skrevet. Den skal aldri presenteres som dokumentets dato."""
    resultat = finn_dokumentdato([_kandidat("2026-01-05", "mottatt")])
    assert resultat["dato"] is None


def test_datert_etikett_gjenkjennes():
    resultat = _dokumentdato("Vi viser til vårt brev datert 12.06.2026 i saken.")
    assert resultat["dato"] == "2026-06-12"
    assert resultat["type"] == "dokumentdato"


def test_soknad_datert_forblir_soknadsdato():
    """«søknad datert» må ikke fanges av den nye «datert»-etiketten —
    mer spesifikke mønstre står først og skal vinne."""
    datoer = sett_dato_roller(
        klassifiser_datoer("Vi har mottatt din søknad datert 01.05.2026."))
    assert datoer[0]["type"] == "soknadsdato"


# ---------- naken dato uten etikett: øverst og ved signaturen ----------
_ERKLARING = """Egenerklæring om sykefravær

Jeg bekrefter at opplysningene er riktige. Fraværet gjaldt perioden
01.03.2026 til 10.03.2026. Jeg ble sykmeldt av lege den 02.03.2026.
Erklæringen leveres til arbeidsgiver snarest mulig etter fraværet.
Ytterligere dokumentasjon ettersendes ved behov innen fristen 20.03.2026.

Oslo, 15.03.2026

Ola Nordmann
(sign.)
"""


def test_signaturblokk_nederst_blir_dokumentdato():
    """«Oslo, 15.03.2026 … (sign.)» nederst ER dokumentets dato — mens
    sykefraværsperioden og fristen over hører til innholdet."""
    resultat = _dokumentdato(_ERKLARING)
    assert resultat["dato"] == "2026-03-15"
    assert resultat["type"] == "signaturdato_sannsynlig"
    assert resultat["kilde"] == "posisjon"


def test_sted_komma_dato_gjenkjennes_uten_etikett():
    resultat = _dokumentdato(_ERKLARING)
    assert "stedsnavn" in resultat["begrunnelse"].lower()


def test_naken_dato_oeverst_uten_etikett():
    """Brevhode med avsender- OG mottakerblokk: datoen kommer langt uti
    teksten, men fortsatt på en av de første LINJENE. Tegnbasert grense
    (den gamle) mistet den; linjebasert finner den."""
    resultat = _dokumentdato(
        "Kommunen\nPostboks 123\n0150 OSLO\n\n"
        "Ola Nordmann\nStorgata 1\n0155 OSLO\n\n"
        "24.02.2026\n\n"
        "Vedrørende din henvendelse om barnehageplass fra 01.08.2026.\n"
        "Vi behandler saken snarest og svarer deg skriftlig innen "
        "15.04.2026 uansett.\n")
    assert resultat["dato"] == "2026-02-24"
    assert resultat["type"] == "brevdato_sannsynlig"


def test_dato_alene_nederst_begrunnes_som_signatur_ikke_toppen():
    """I et KORT dokument er de første 14 linjene også de siste. Uten
    vernet fikk en dato ved underskriften begrunnelsen «øverst i
    dokumentet» — riktig dato, men usann forklaring."""
    resultat = _dokumentdato(
        "Rapport om aktiviteten\n\n"
        "I perioden 01.01.2026 til 31.01.2026 ble det gjennomført tolv\n"
        "møter med deltakerne. Neste evaluering er planlagt til 15.06.2026\n"
        "og skal omfatte hele tiltaket. Rapporten sendes til partene.\n\n"
        "10.02.2026\n")
    assert resultat["dato"] == "2026-02-10"
    assert resultat["type"] == "signaturdato_sannsynlig"
    assert "nederst" in resultat["begrunnelse"]


# ---------- datospennet FRA–TIL ----------
_BUNKE = """[Side 1 av 3]
NAV Arbeid og ytelser

12.06.2026

Vedtak om dagpenger for perioden 01.07.2026 til 31.12.2026.
Klagefrist er 05.07.2026 og må overholdes av alle parter i saken.
Ta kontakt ved spørsmål om vedtaket eller utbetalingene dine.
[Side 2 av 3]
Arbeidsgiver AS

20.07.2026

Bekreftelse på ansettelsesforhold for søkeren i vår virksomhet her.
Vedkommende har vært ansatt siden 01.02.2024 i full stilling hos oss.
Vi bekrefter at opplysningene i skjemaet er korrekte og fullstendige.
[Side 3 av 3]
Erklæring fra søkeren om egne forhold i saken som er til behandling.
Jeg bekrefter at alle opplysninger jeg har gitt er riktige og komplette.
Ingen vesentlige endringer har skjedd siden søknaden ble sendt inn.

Bergen, 05.08.2026

Ola Nordmann
(sign.)
"""


def test_ett_brev_gir_fra_lik_til():
    """Ett dokument har ett datopunkt — spennet skal ikke finne på noe."""
    periode = _dokumentdato(
        "Kommunen\nPostboks 123\n\n12.06.2026\n\n"
        "Vi viser til din henvendelse om plass fra 01.08.2026 og svarer "
        "deg skriftlig innen 15.07.2026.\n")["periode"]
    assert periode["fra"] == periode["til"] == "2026-06-12"
    assert periode["flere_dokumenter"] is False


def test_bunke_gir_spenn_fra_foerste_til_siste():
    periode = _dokumentdato(_BUNKE)["periode"]
    assert periode["fra"] == "2026-06-12"
    assert periode["til"] == "2026-08-05"
    assert periode["flere_dokumenter"] is True
    assert periode["antall"] == 3


def test_bunke_gir_dato_per_side():
    """Poenget med flersidige filer: hvilket dokument hører til hvilken
    side. Uten dette er et spenn bare to tall uten forklaring."""
    per_side = _dokumentdato(_BUNKE)["periode"]["per_side"]
    assert [(s["side"], s["dato"]) for s in per_side] == [
        (1, "2026-06-12"), (2, "2026-07-20"), (3, "2026-08-05")]


def test_brevdato_finnes_oeverst_paa_HVER_side():
    """«Øverst» måles per SIDE. Målt mot hele filen ville brevhodet på
    side 2 aldri blitt funnet — og bunken fått feil spenn."""
    datoer = sett_dato_roller(klassifiser_datoer(_BUNKE))
    side2 = [d for d in datoer if d["side"] == 2 and d["rolle"] == ROLLE_DOKUMENT]
    assert [d["dato"] for d in side2] == ["2026-07-20"]
    assert side2[0]["type"] == "brevdato_sannsynlig"


def test_signaturblokk_finnes_nederst_paa_SIN_side():
    datoer = sett_dato_roller(klassifiser_datoer(_BUNKE))
    side3 = [d for d in datoer if d["side"] == 3 and d["rolle"] == ROLLE_DOKUMENT]
    assert [d["dato"] for d in side3] == ["2026-08-05"]


def test_innholdsdatoer_holdes_utenfor_spennet():
    """Periodene og fristene i vedtaket (01.07.2026–31.12.2026,
    05.07.2026, 01.02.2024) skal ikke påvirke dokumentspennet."""
    periode = _dokumentdato(_BUNKE)["periode"]
    alle = {s["dato"] for s in periode["per_side"]}
    assert "2024-02-01" not in alle and "2026-07-05" not in alle
    assert periode["fra"] == "2026-06-12"      # ikke 01.02.2024


def test_bunke_varsles_men_uten_dobbel_advarsel():
    resultat = _dokumentdato(_BUNKE)
    assert "flere daterte dokumenter" in resultat["advarsel"]
    # spenn-advarselen forklarer allerede uenigheten — ikke gjenta den
    assert "like sterke kandidater" not in resultat["advarsel"]


def test_ingen_dokumentdato_gir_tomt_periodeskjelett():
    """Uten dokumentdato finnes ingen periode — men `periode` er et
    OBJEKT, ikke null.

    Testen krevde tidligere `periode is None`. Det var samme feil som
    R118 forbyr: et nestet objekt som blir null tar med seg alle stiene
    under seg, så en robot som leser `periode.fra` krasjer på det første
    udaterte dokumentet. Nå står skjelettet med null-verdier."""
    resultat = finn_dokumentdato([_kandidat("2026-07-05", "frist")])
    assert resultat["dato"] is None
    assert resultat["periode"] == {"fra": None, "til": None, "antall": 0,
                                   "per_side": [],
                                   "flere_dokumenter": False}


def test_dokumentdatoen_har_samme_nokler_med_og_uten_funn():
    """Kjernen i R118, målt direkte på de to grenene.

    Tom-grenen manglet «type_kodet» og «rolle_kodet» — ikke som null,
    men BORTE. 12 nøkler ble 10, og en robot som leser
    `felter.dokumentdato.type_kodet.kode` virket på hvert datert
    dokument og krasjet på det første udaterte."""
    med = finn_dokumentdato([_kandidat("2026-07-05", "dokumentdato")])
    uten = finn_dokumentdato([_kandidat("2026-07-05", "frist")])
    assert sorted(med) == sorted(uten), (
        f"ulike nøkkelsett:\n  med funn: {sorted(med)}\n"
        f"  uten funn: {sorted(uten)}")
    assert uten["type_kodet"] == {"kode": None, "term": None}
    assert uten["rolle_kodet"] == {"kode": None, "term": None}


# ---------- alder (fortsatt tilgjengelig som hjelpefunksjon) ----------
def test_alder_regnes_fra_dokumentdatoen():
    i_dag = date(2026, 7, 28)
    assert dokumentets_alder("2026-07-28", i_dag)["dager"] == 0
    assert dokumentets_alder("2025-07-28", i_dag)["dager"] == 365


def test_fremtidig_dato_flagges_i_stedet_for_negativt_tall():
    alder = dokumentets_alder("2026-12-01", date(2026, 7, 28))
    assert alder["fremtidig"] is True
    assert "FRAM I TID" in alder["tekst"]


def test_alder_taaler_soppel():
    assert dokumentets_alder(None)["dager"] is None
    assert dokumentets_alder("tull")["dager"] is None
    assert dokumentets_alder("2026-02-31")["dager"] is None      # finnes ikke


# ---------- OCR-robusthet i datodetektoren (R61) ----------
def _datoer(tekst):
    from delt.tekstuttrekk import finn_alle_datoer
    return finn_alle_datoer(tekst)


@pytest.mark.parametrize("tekst,forventet", [
    # OCR limer ofte datoen til nabotekst på kvitteringer. Før R61 fant
    # \b ingen ordgrense mellom to bokstaver/sifre og forkastet datoen.
    ("DATO12.06.2026", ["2026-06-12"]),
    ("12.06.2026kr", ["2026-06-12"]),
    ("12.06.2026KL14:46", ["2026-06-12"]),
    ("Dato12.06.2026Kl14:46", ["2026-06-12"]),
])
def test_dato_limt_til_nabotegn_fanges(tekst, forventet):
    assert _datoer(tekst) == forventet


@pytest.mark.parametrize("tekst,forventet", [
    # OCR mister mellomrommet rundt månedsnavnet.
    ("08.juni 2026", ["2026-06-08"]),
    ("8.juni.2026", ["2026-06-08"]),
    ("1. desember 2026kl", ["2026-12-01"]),
])
def test_maanedsnavn_uten_mellomrom_fanges(tekst, forventet):
    assert _datoer(tekst) == forventet


@pytest.mark.parametrize("tekst", [
    "20261234",              # ren tallmengde — ingen dato
    "kontonr 12345678910",   # identifikator, ikke dato
    "12.06.20261",           # år limt til ekstra siffer — forkastes
])
def test_robusthet_gir_ingen_falske_datoer(tekst):
    """Lookarounds skal bare tillate BOKSTAV-naboer, aldri plukke en
    «dato» ut av en ren siffermengde."""
    assert _datoer(tekst) == []


# ---------- kodede kategorifelter {kode, term} (AAREG-stil) ----------
def test_kodeverk_gir_kode_og_term():
    assert kodeverk("vedtaksdato", _TYPE_TERM) == {
        "kode": "vedtaksdato", "term": "Vedtaksdato"}


def test_kodeverk_ukjent_kode_faller_tilbake_til_seg_selv():
    """En ny type skal aldri mangle en lesbar verdi."""
    assert kodeverk("helt_ny_type", _TYPE_TERM) == {
        "kode": "helt_ny_type", "term": "helt_ny_type"}


def test_kodeverk_uten_kode_gir_PARET_med_null():
    assert kodeverk(None, _TYPE_TERM) == {"kode": None, "term": None}
    assert kodeverk(None, _ROLLE_TERM) == {"kode": None, "term": None}


def test_datoer_faar_kodede_felter_i_tillegg_til_raa():
    datoer = sett_dato_roller(klassifiser_datoer(
        "Vedtaksdato: 12.06.2026\nKlagefrist innen 05.07.2026.\n"))
    vedtak = next(d for d in datoer if d["dato"] == "2026-06-12")
    # rå strengfelt uendret (bakoverkompatibelt)
    assert vedtak["type"] == "vedtaksdato"
    assert vedtak["rolle"] == ROLLE_DOKUMENT
    # kodede par lagt til
    assert vedtak["type_kodet"] == {"kode": "vedtaksdato", "term": "Vedtaksdato"}
    assert vedtak["rolle_kodet"]["kode"] == "dokument"
    assert vedtak["rolle_kodet"]["term"]


def test_dokumentdato_har_kodede_felter():
    resultat = _dokumentdato("Vedtaksdato: 12.06.2026\nFrist 05.07.2026.\n")
    assert resultat["type"] == "vedtaksdato"          # rå, uendret
    assert resultat["type_kodet"] == {"kode": "vedtaksdato",
                                      "term": "Vedtaksdato"}
    assert resultat["rolle_kodet"]["kode"] == "dokument"


def test_alternativer_har_kodet_type():
    resultat = finn_dokumentdato([
        _kandidat("2026-02-01", "pdf_opprettet", side=None),
        _kandidat("2026-06-12", "vedtaksdato"),
    ])
    alt = resultat["alternativer"][0]
    assert alt["type"] == "pdf_opprettet"
    assert alt["type_kodet"]["kode"] == "pdf_opprettet"
    assert alt["type_kodet"]["term"]


def test_roller_settes_paa_alle_datoer():
    datoer = sett_dato_roller(klassifiser_datoer(
        "Vedtaksdato: 12.06.2026\nKlagefrist: innen 05.07.2026.\n"))
    assert all("rolle" in d for d in datoer)
    roller = {d["dato"]: d["rolle"] for d in datoer}
    assert roller["2026-06-12"] == ROLLE_DOKUMENT
    assert roller["2026-07-05"] == ROLLE_INNHOLD
