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

sys.path.insert(0, ".")

from delt.tekstuttrekk import (ROLLE_BEHANDLING, ROLLE_DOKUMENT,
                               ROLLE_INNHOLD, dokumentets_alder,
                               finn_dokumentdato,
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
    assert resultat["dato"] == "12.06.2026"
    assert resultat["type"] == "vedtaksdato"
    assert resultat["konfidens"] == "hoy"


def test_dato_overst_paa_side_1_blir_brevdato():
    resultat = _dokumentdato(
        "15.03.2026\n\nTil Ola Nordmann\nUtbetaling skjer 20.04.2026.\n")
    assert resultat["dato"] == "15.03.2026"
    assert resultat["kilde"] == "posisjon"


def test_bare_innholdsdatoer_gir_aerlig_ingen():
    """Ingen dokumentdato er et GYLDIG svar — bedre enn en gjetning."""
    resultat = finn_dokumentdato([
        _kandidat("05.07.2026", "frist"),
        _kandidat("03.04.1985", "fodselsdato"),
        _kandidat("01.07.2026", "periode_start"),
    ])
    assert resultat["dato"] is None
    assert resultat["konfidens"] == "ingen"
    assert "innholdet" in resultat["begrunnelse"]


def test_etikett_slaar_pdf_metadata():
    resultat = finn_dokumentdato([
        _kandidat("01.02.2026", "pdf_opprettet", side=None),
        _kandidat("12.06.2026", "vedtaksdato"),
    ])
    assert resultat["dato"] == "12.06.2026"
    # den tapende kandidaten skal fortsatt være synlig, ikke forsvinne
    assert "01.02.2026" in [a["dato"] for a in resultat["alternativer"]]


def test_pdf_metadata_paa_skannet_dokument_merkes_som_skannedato():
    skannet = finn_dokumentdato(
        [_kandidat("01.02.2026", "pdf_opprettet", side=None)], ocr_brukt=True)
    assert skannet["dato"] == "01.02.2026"
    assert skannet["konfidens"] == "lav"
    assert "SKANNEDATOEN" in skannet["advarsel"]


def test_uenighet_mellom_like_sterke_kandidater_varsles():
    resultat = finn_dokumentdato([
        _kandidat("12.06.2026", "vedtaksdato"),
        _kandidat("20.06.2026", "utstedt"),
    ])
    assert resultat["dato"] == "12.06.2026"      # første vinner
    assert "ULIKE datoer" in resultat["advarsel"]
    assert "20.06.2026" in resultat["advarsel"]


def test_haandskrevet_dokumentdato_nedgraderes():
    resultat = finn_dokumentdato(
        [_kandidat("12.06.2026", "vedtaksdato", skrevet_for_hand=True)],
        ocr_brukt=True)
    assert resultat["konfidens"] == "middels"    # ned fra «hoy»
    assert "håndskrevet" in resultat["advarsel"]


def test_mottatt_dato_blir_ikke_dokumentdato():
    """«Mottatt 05.01.2026» sier når NAV fikk brevet — ikke når det ble
    skrevet. Den skal aldri presenteres som dokumentets dato."""
    resultat = finn_dokumentdato([_kandidat("05.01.2026", "mottatt")])
    assert resultat["dato"] is None


def test_datert_etikett_gjenkjennes():
    resultat = _dokumentdato("Vi viser til vårt brev datert 12.06.2026 i saken.")
    assert resultat["dato"] == "12.06.2026"
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
    assert resultat["dato"] == "15.03.2026"
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
    assert resultat["dato"] == "24.02.2026"
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
    assert resultat["dato"] == "10.02.2026"
    assert resultat["type"] == "signaturdato_sannsynlig"
    assert "nederst" in resultat["begrunnelse"]


# ---------- dokumentets alder ----------
def test_alder_regnes_fra_dokumentdatoen():
    i_dag = date(2026, 7, 28)
    assert dokumentets_alder("28.07.2026", i_dag)["dager"] == 0
    assert dokumentets_alder("28.07.2026", i_dag)["tekst"] == "datert i dag"
    assert dokumentets_alder("28.07.2025", i_dag)["dager"] == 365
    assert "1 år" in dokumentets_alder("28.07.2025", i_dag)["tekst"]
    gammelt = dokumentets_alder("01.01.2020", i_dag)
    assert gammelt["dager"] == 2400 and gammelt["aar"] == 6.57


def test_fremtidig_dato_flagges_i_stedet_for_negativt_tall():
    alder = dokumentets_alder("01.12.2026", date(2026, 7, 28))
    assert alder["fremtidig"] is True
    assert "FRAM I TID" in alder["tekst"]


def test_alder_taaler_soppel():
    assert dokumentets_alder(None) is None
    assert dokumentets_alder("tull") is None
    assert dokumentets_alder("31.02.2026") is None      # finnes ikke


def test_dokumentdato_har_alder_med():
    resultat = _dokumentdato("Vedtaksdato: 12.06.2026\nFrist 05.07.2026.\n")
    assert resultat["alder"] is not None
    assert resultat["alder"]["dager"] >= 0


def test_ingen_dokumentdato_gir_ingen_alder():
    resultat = finn_dokumentdato([_kandidat("05.07.2026", "frist")])
    assert resultat["dato"] is None and resultat["alder"] is None


def test_roller_settes_paa_alle_datoer():
    datoer = sett_dato_roller(klassifiser_datoer(
        "Vedtaksdato: 12.06.2026\nKlagefrist: innen 05.07.2026.\n"))
    assert all("rolle" in d for d in datoer)
    roller = {d["dato"]: d["rolle"] for d in datoer}
    assert roller["12.06.2026"] == ROLLE_DOKUMENT
    assert roller["05.07.2026"] == ROLLE_INNHOLD
