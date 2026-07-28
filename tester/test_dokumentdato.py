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

sys.path.insert(0, ".")

from delt.tekstuttrekk import (ROLLE_BEHANDLING, ROLLE_DOKUMENT,
                               ROLLE_INNHOLD, finn_dokumentdato,
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


def test_roller_settes_paa_alle_datoer():
    datoer = sett_dato_roller(klassifiser_datoer(
        "Vedtaksdato: 12.06.2026\nKlagefrist: innen 05.07.2026.\n"))
    assert all("rolle" in d for d in datoer)
    roller = {d["dato"]: d["rolle"] for d in datoer}
    assert roller["12.06.2026"] == ROLLE_DOKUMENT
    assert roller["05.07.2026"] == ROLLE_INNHOLD
