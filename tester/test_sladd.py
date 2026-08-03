"""
POST /sladd — sladding av det som kan BEVISES, og bare det.

Testene dekker BEGGE feilretninger, for begge er skadelige:
  * det som SKAL sladdes må forsvinne (lekkasje = personvernbrudd)
  * det som IKKE skal sladdes må stå (oversladding = fjernet saksinnhold)

Og grensene må sies høyt: navn/adresser dekkes ikke, og OCR-tekst kan
ha feilleste sifre som gjør at sjekksummen ikke slår til.
"""
import sys
import types

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

from delt.tekstuttrekk import (SLADD_TYPER, finn_sladdeomraader, sladd_tekst)

import dokument_api as api


# Gyldige testverdier (samme som ellers i testene — syntetiske, men
# består kontrollene)
def _gyldig_fnr() -> str:
    """Syntetisk fnr med korrekte kontrollsifre, regnet uavhengig av
    koden som testes (samme metode som test_kvittering_validering)."""
    v1 = [3, 7, 6, 1, 8, 9, 4, 5, 2]
    v2 = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    for base in range(10_000_000, 10_100_000):
        fnr9 = f"010190{base % 1000:03d}"
        k1 = 11 - sum(int(fnr9[i]) * v1[i] for i in range(9)) % 11
        if k1 == 11:
            k1 = 0
        if k1 == 10:
            continue
        fnr10 = fnr9 + str(k1)
        k2 = 11 - sum(int(fnr10[i]) * v2[i] for i in range(10)) % 11
        if k2 == 11:
            k2 = 0
        if k2 == 10:
            continue
        return fnr10 + str(k2)
    raise AssertionError("fant ikke gyldig test-fnr")


FNR = _gyldig_fnr()
ORGNR = "889000007"          # syntetisk (fra testbunken), mod11-gyldig


# ------------------------------------------------------------------ #
#  Retning 1: det som SKAL sladdes forsvinner                          #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("tekst,type_", [
    (f"Fødselsnummer: {FNR} er registrert", "fodselsnummer"),
    (f"Org. Nr: {ORGNR}", "organisasjonsnummer"),
    ("Ring oss på 22 33 44 55 i dag", "telefon"),
    ("kontakt ola.nordmann@nav.no for info", "epost"),
    ("KID: 2345676", "kid"),
])
def test_bevist_identifikator_sladdes(tekst, type_):
    sladdet, antall = sladd_tekst(tekst)
    assert f"[SLADDET {type_}]" in sladdet
    assert antall.get(type_, 0) >= 1


def test_gruppert_fnr_sladdes_helt():
    """«010190 12345»-formen: hele det grupperte området må bort, ikke
    bare de sammenhengende sifrene."""
    gruppert = FNR[:6] + " " + FNR[6:]
    sladdet, _ = sladd_tekst(f"fnr {gruppert} slutt")
    assert FNR[:6] not in sladdet
    assert FNR[6:] not in sladdet
    assert "[SLADDET fodselsnummer]" in sladdet


def test_alle_forekomster_sladdes():
    tekst = f"Første: {FNR}. Andre gang: {FNR}."
    sladdet, antall = sladd_tekst(tekst)
    assert FNR not in sladdet
    assert antall["fodselsnummer"] == 2


# ------------------------------------------------------------------ #
#  Retning 2: det som IKKE skal sladdes står                           #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("tekst", [
    "Vedtak datert 01.01.2024 114 kroner utbetales",   # dato+beløp-fella
    "Saksnr: 21/12345 behandles",
    "Beløpet er kr 12 345,50 per måned",
    "Møtet er 12.06.2026 klokken 14:28",
    "Postnummer 0181 Oslo",
    "Side 3 av 12",
])
def test_lovlig_innhold_sladdes_ikke(tekst):
    """Dato-/beløpsvakten fra _tallkandidater gjelder også her: en falsk
    positiv i sladding FJERNER lovlig saksinnhold."""
    sladdet, antall = sladd_tekst(tekst)
    assert sladdet == tekst
    assert antall == {}


def test_ugyldig_fnr_sladdes_ikke():
    """11 sifre som IKKE består mod11 er ikke et fødselsnummer — å
    sladde det ville skjult f.eks. et referansenummer."""
    sladdet, antall = sladd_tekst("referanse 12345678901 i saken")
    assert "12345678901" in sladdet
    assert antall == {}


def test_navn_sladdes_ikke_og_det_er_med_vilje():
    """Navn KAN ikke bevises deterministisk — de skal stå, og grensen
    deklareres i API-svaret (testes under)."""
    sladdet, _ = sladd_tekst("Ola Nordmann søker om dagpenger")
    assert "Ola Nordmann" in sladdet


def test_kid_etiketten_staar_igjen():
    """Leseren skal SE at det sto et KID der — bare nummeret sladdes."""
    sladdet, _ = sladd_tekst("KID: 2345676 ved betaling")
    assert "KID" in sladdet
    assert "2345676" not in sladdet


# ------------------------------------------------------------------ #
#  Typeutvalg og posisjoner                                            #
# ------------------------------------------------------------------ #

def test_typer_avgrenser_sladdingen():
    tekst = f"fnr {FNR}, ring 22 33 44 55"
    sladdet, antall = sladd_tekst(tekst, typer=["telefon"])
    assert FNR in sladdet                    # ikke valgt → står
    assert "[SLADDET telefon]" in sladdet
    assert list(antall) == ["telefon"]


def test_omraader_er_sortert_uten_overlapp():
    tekst = f"a {FNR} b {ORGNR} c ola@nav.no"
    omraader = finn_sladdeomraader(tekst)
    for (s1, e1, _), (s2, e2, _) in zip(omraader, omraader[1:]):
        assert e1 <= s2, "overlappende sladdeområder"
    assert [t for _, _, t in omraader] == \
        ["fodselsnummer", "organisasjonsnummer", "epost"]


def test_sladd_typer_konstanten_er_kontrakten():
    assert set(SLADD_TYPER) == {"fodselsnummer", "kontonummer",
                                "organisasjonsnummer", "kid", "telefon",
                                "epost"}


# ------------------------------------------------------------------ #
#  Endepunktet                                                         #
# ------------------------------------------------------------------ #

def _fang_handler():
    h = api.Handler.__new__(api.Handler)
    h.headers = {}
    h.path = "/sladd"
    h.command = "POST"
    h.client_address = ("127.0.0.1", 4321)
    fanget = {}
    h.send_response = lambda k: fanget.__setitem__("kode", k)
    h.send_header = lambda n, v: None
    h.end_headers = lambda: None
    h.wfile = types.SimpleNamespace(
        write=lambda b: fanget.__setitem__(
            "kropp", __import__("json").loads(b)))
    h._cors_origin = lambda: None
    return h, fanget


def test_endepunktet_sladder_og_deklarerer_grensene():
    h, fanget = _fang_handler()
    tekst = f"Ola Nordmann, fnr {FNR}, tlf 22 33 44 55"
    h._sladd("brev.txt", "tekst", tekst, None, {})
    assert fanget["kode"] == 200
    svar = fanget["kropp"]
    assert FNR not in svar["sladdet_tekst"]
    assert "Ola Nordmann" in svar["sladdet_tekst"]
    assert svar["antall_sladdet"] == 2
    assert svar["ikke_dekket"] == ["navn", "adresser"]
    # grensen står i SELVE svaret, ikke bare i dokumentasjonen
    assert "offentleglova" in svar["advarsel"]
    assert svar["kilde"] == "deterministisk"


def test_endepunktet_ukjent_type_gir_400():
    h, fanget = _fang_handler()
    h._sladd("brev.txt", "tekst", "noe tekst", None,
             {"typer": "personnummer"})
    assert fanget["kode"] == 400
    assert "fodselsnummer" in fanget["kropp"]["feil"]


def test_endepunktet_typer_utvalg():
    h, fanget = _fang_handler()
    h._sladd("brev.txt", "tekst", f"fnr {FNR} tlf 22 33 44 55", None,
             {"typer": "fodselsnummer"})
    svar = fanget["kropp"]
    assert "[SLADDET fodselsnummer]" in svar["sladdet_tekst"]
    assert "22 33 44 55" in svar["sladdet_tekst"]
    assert svar["typer_valgt"] == ["fodselsnummer"]


def test_endepunktet_ukjent_feltnavn_meldes():
    h, fanget = _fang_handler()
    h._sladd("brev.txt", "tekst", "tekst", None, {"types": "epost"})
    assert fanget["kode"] == 200
    assert any("types" in a for a in fanget["kropp"]["advarsler"])


def test_sladd_er_med_i_openapi():
    """Samme vakt som resten: et udokumentert endepunkt finnes ikke."""
    spekk = api._openapi()
    assert "/sladd" in spekk["paths"]
    assert "SladdSvar" in spekk["components"]["schemas"]
