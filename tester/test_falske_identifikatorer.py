"""
Regresjonstester for den ALVORLIGSTE feilen systemrevisjonen fant:
sifferskanningen limte sammen NABOTALL og produserte oppdiktede, men
mod11-GYLDIGE fødselsnummer og organisasjonsnummer.

«Vedtak datert 01.01.2024 114 kroner» ble til «01012024114». Det består
mod11, så ingen validering stoppet det. Nummeret gikk videre inn i
prompten merket «KONTROLLERT av kode (sjekksum/format) — bruk disse i
felter som ber om dem», og havnet i fødselsnummerfeltet i
skjemautfyllingen. Merkingen desarmerte nettopp den menneskelige
kontrollen som ellers kunne fanget det: et oppdiktet personnummer — som
godt kan tilhøre en helt annen, virkelig borger — presentert som
kodekontrollert.

Vakten: en kandidat forkastes hvis den overlapper en dato eller et beløp.
Testene her holder BEGGE sider fast — de oppdiktede skal bli borte, og
alle de ekte grupperingene skal fortsatt finnes.
"""
import sys

import pytest

sys.path.insert(0, ".")

from delt.tekstuttrekk import (er_gyldig_fnr, er_gyldig_orgnr,
                               finn_alle_fodselsnummer,
                               finn_alle_kontonummer,
                               finn_alle_organisasjonsnummer,
                               strukturert_uttrekk)

# Verifisert mod11-gyldig (syntetisk, ikke en reell person)
GYLDIG_FNR = "18052744241"
GYLDIG_ORGNR = "923609016"


def test_testdataene_er_faktisk_gyldige():
    """Uten denne ville resten av fila kunne bestå med ugyldige tall."""
    assert er_gyldig_fnr(GYLDIG_FNR)
    assert er_gyldig_orgnr(GYLDIG_ORGNR)


# ---------- selve regresjonen ----------
@pytest.mark.parametrize("tekst", [
    "Vedtak datert 01.01.2024 114 kroner utbetalt",
    "Dato 01.01.2024 386 stk",
    "Frist 01.01.2024 033 vedlegg",
])
def test_dato_pluss_nabotall_blir_aldri_fodselsnummer(tekst):
    """Datoen og tallet etter er TO tall, ikke ett ellevesifret."""
    assert finn_alle_fodselsnummer(tekst) == []


@pytest.mark.parametrize("tekst", [
    "Beløp kr 103 456 789 på konto",
    "Utbetalt 103 456 789 kroner",
    "Sum 103 456 789 NOK",
])
def test_belop_blir_aldri_organisasjonsnummer(tekst):
    """«103 456 789» er et beløp her — grupperingen ser ut som et orgnr,
    men valutaordet forteller hva det faktisk er."""
    assert finn_alle_organisasjonsnummer(tekst) == []


def test_oppdiktet_nummer_naar_heller_ikke_strukturert_uttrekk():
    """Samme defekt traff «identifikatorer»-utdata, ikke bare prompten."""
    s = strukturert_uttrekk("Vedtak datert 01.01.2024 114 kroner utbetalt")
    assert s["identifikatorer"]["fodselsnummer"] == []
    assert s["identifikatorer"]["organisasjonsnummer"] == []


# ---------- ekte identifikatorer skal overleve vakten ----------
@pytest.mark.parametrize("tekst", [
    f"Fødselsnummer: {GYLDIG_FNR}",
    f"Fnr {GYLDIG_FNR[:6]} {GYLDIG_FNR[6:]}",              # 6+5
    f"Personnummer {GYLDIG_FNR[:6]} {GYLDIG_FNR[6:9]} {GYLDIG_FNR[9:]}",  # 6+3+2
    f"Fnr {GYLDIG_FNR[:4]}.{GYLDIG_FNR[4:6]}.{GYLDIG_FNR[6:]}",           # punktum
])
def test_ekte_fodselsnummer_finnes_i_alle_grupperinger(tekst):
    assert finn_alle_fodselsnummer(tekst) == [GYLDIG_FNR]


@pytest.mark.parametrize("tekst", [
    f"Org.nr {GYLDIG_ORGNR}",
    f"Organisasjonsnummer {GYLDIG_ORGNR[:3]} {GYLDIG_ORGNR[3:6]} {GYLDIG_ORGNR[6:]}",
    f"Orgnr {GYLDIG_ORGNR[:4]} {GYLDIG_ORGNR[4:]}",
])
def test_ekte_organisasjonsnummer_finnes_i_alle_grupperinger(tekst):
    assert finn_alle_organisasjonsnummer(tekst) == [GYLDIG_ORGNR]


def test_ekte_nummer_rett_etter_en_dato_finnes_fortsatt():
    """Vakten skal utelukke tall som OVERLAPPER en dato — ikke alt som
    står i nærheten av en. Ellers ville et vedtaksbrev med både dato og
    fødselsnummer mistet nummeret."""
    tekst = f"Vedtaksdato 12.06.2026. Fødselsnummer {GYLDIG_FNR}."
    assert finn_alle_fodselsnummer(tekst) == [GYLDIG_FNR]


def test_ekte_nummer_rett_etter_et_belop_finnes_fortsatt():
    tekst = f"Utbetalt 12 500 kroner. Org.nr {GYLDIG_ORGNR}."
    assert finn_alle_organisasjonsnummer(tekst) == [GYLDIG_ORGNR]


def test_helt_dokument_gir_bare_de_ekte():
    """Realistisk vedtaksbrev: datoer, beløp OG ekte identifikatorer."""
    tekst = (
        "NAV Arbeid og ytelser\n"
        "Vedtaksdato: 12.06.2026\n"
        f"Fødselsnummer: {GYLDIG_FNR}\n"
        f"Org.nr {GYLDIG_ORGNR}\n"
        "Dagpenger for perioden 01.07.2026 til 31.12.2026.\n"
        "Du får utbetalt 12 500 kroner per måned.\n"
        "Klagefrist: innen 05.07.2026 114 dager etter mottak.\n")
    assert finn_alle_fodselsnummer(tekst) == [GYLDIG_FNR]
    assert finn_alle_organisasjonsnummer(tekst) == [GYLDIG_ORGNR]
    # kontonummer deler kandidatstrømmen med fnr — ingen skal dukke opp
    assert finn_alle_kontonummer(tekst) == []
