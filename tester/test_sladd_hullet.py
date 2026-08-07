"""
`/sladd` sier fra om det den IKKE klarte å sladde.

Målt på et dokument med fem MERKEDE identifikatorer der fire feilet
kontrollsifferet:

    ok: true,  antall_sladdet: 2,  advarsler: []
    funn: [telefon, epost]

Tre merkede numre sto igjen i klartekst, og HVERT maskinlesbart felt så
like friskt ut som på et rent dokument. Eneste måten å oppdage
lekkasjen på var å lese `sladdet_tekst` selv — altså å gjøre sladdingen
om igjen for å kontrollere sladdingen.

Årsaken er en bevisst design: `sladd_tekst` fjerner bare det den kan
BEVISE (mod11/mod10). Består ikke kontrollsifferet, emitteres ingen
område, og etiketten ved siden av konsulteres aldri. Det er riktig —
en falsk positiv FJERNER lovlig innhold. Feilen var at hullet ikke ble
MELDT.

`funn` teller hva som ble FJERNET. `mistenkt_usladdet` sier hva som ble
MISSET. `sladding_fullstendig` er den ene boolen en robot kan rute på.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api
import syntetiske_nummer
from delt.tekstuttrekk import (finn_mistenkt_usladdet, finn_sladdeomraader,
                               sladd_tekst)

GYLDIG_FNR = syntetiske_nummer.lag_fnr()
GYLDIG_KONTO = syntetiske_nummer.lag_kontonummer()


def _brekk(nummer: str) -> str:
    """Et gyldig nummer med ODELAGT kontrollsiffer.

    Bygges, ikke skrives: portabilitetsvakten tillater ingen
    ellevesifrede literaler i kildekoden — og den tok denne fila.
    Aa avlede fra et gyldig nummer er dessuten aerligere enn en
    haandskrevet streng: vi VET at det bare er sjekksummen som er
    feil."""
    siste = str((int(nummer[-1]) + 1) % 10)
    return nummer[:-1] + siste


UGYLDIG_KONTO = _brekk(GYLDIG_KONTO)
UGYLDIG_FNR = _brekk(GYLDIG_FNR)

# Merkede numre som IKKE består kontrollsifferet — skrivefeil,
# utenlandsk format eller OCR-feillesning.
UGYLDIG = f"""[Side 1 av 1]
NAV
Fodselsnummer: {UGYLDIG_FNR}
Kontonummer: {UGYLDIG_KONTO}
Organisasjonsnummer: 999888777
KID: 1234567891
Telefon: 99887766
"""

RENT = f"""[Side 1 av 1]
NAV
Fodselsnummer: {GYLDIG_FNR}
Kontonummer: {GYLDIG_KONTO}
"""


# ------------------------------------------------------------------ #
#  1. Funksjonen                                                       #
# ------------------------------------------------------------------ #

def test_merket_men_ugyldig_blir_meldt():
    funn = finn_mistenkt_usladdet(UGYLDIG, finn_sladdeomraader(UGYLDIG))
    typer = {p["type"] for p in funn}
    assert "fodselsnummer" in typer
    assert "kontonummer" in typer
    assert "organisasjonsnummer" in typer
    assert "kid" in typer


def test_gyldig_og_sladdet_meldes_ikke():
    """Speilet — uten dette ville alt blitt meldt, og feltet vært verdiløst."""
    omraader = finn_sladdeomraader(RENT)
    funn = finn_mistenkt_usladdet(RENT, omraader)
    assert funn == [], f"sladdet innhold skal ikke meldes: {funn}"


def test_hvert_funn_sier_hva_hvor_og_hvorfor():
    """En liste uten begrunnelse er en liste ingen tør handle på."""
    funn = finn_mistenkt_usladdet(UGYLDIG, finn_sladdeomraader(UGYLDIG))
    assert funn
    for p in funn:
        assert set(p) == {"type", "etikett", "posisjon", "lengde", "grunn"}
        assert p["etikett"], "etiketten som sto der må navngis"
        assert isinstance(p["posisjon"], int)
        assert p["grunn"] in ("kontrollsiffer_feilet", "feil_lengde")


def test_funnene_er_sortert_etter_posisjon():
    """En klient som viser dem for et menneske skal slippe å sortere."""
    funn = finn_mistenkt_usladdet(UGYLDIG, finn_sladdeomraader(UGYLDIG))
    assert [p["posisjon"] for p in funn] == sorted(
        p["posisjon"] for p in funn)


def test_umerkede_tall_meldes_ikke():
    """Bare det som er TYDELIG merket. Uten etikettkravet ville hvert
    beløp og hver dato blitt meldt som mulig identifikator, og feltet
    druknet i støy."""
    tekst = (f"[Side 1 av 1]\nFaktura {GYLDIG_FNR} av 01.01.2026, "
             f"4500 kr\n")
    assert finn_mistenkt_usladdet(tekst, finn_sladdeomraader(tekst)) == []


# ------------------------------------------------------------------ #
#  2. Svaret                                                           #
# ------------------------------------------------------------------ #

def _sladd(tekst):
    H = api.Handler

    class Fake:
        SLADD_ADVARSEL = H.SLADD_ADVARSEL
        _les_dokument = H._les_dokument
        _sladd = H._sladd

        def __init__(self):
            self.svar = None

        def _svar(self, kode, data, hoder=None):
            self.svar = (kode, data)
            return (kode, data)

    f = Fake()
    f._kappet_advarsel = None
    f._sladd("p.txt", "tekst", tekst, None, {})
    return f.svar[1]


def test_svaret_navngir_det_som_sto_igjen():
    svar = _sladd(UGYLDIG)
    assert svar["mistenkt_usladdet"], (
        "tre merkede numre sto igjen — svaret må si det")
    assert svar["sladding_fullstendig"] is False


def test_rent_dokument_melder_fullstendig():
    """Uten speilet kunne feltet vært hardkodet False og alltid «riktig»."""
    svar = _sladd(RENT)
    assert svar["mistenkt_usladdet"] == []
    assert svar["sladding_fullstendig"] is True


def test_klienten_kan_se_forskjellen_uten_aa_lese_teksten():
    """Kjernen. Før var HVERT maskinlesbart felt likt for de to
    dokumentene, og bare `sladdet_tekst` skilte dem."""
    hullet = _sladd(UGYLDIG)
    rent = _sladd(RENT)
    assert (hullet["sladding_fullstendig"]
            != rent["sladding_fullstendig"]), (
        "et rent og et lekk dokument må kunne skilles maskinelt")


def test_advarselen_kommer_ogsaa_uten_OCR():
    """Advarselen fantes, men lå bak `if ktx.ocr_brukt:`. På et
    tekstlags-PDF er ikke OCR årsaken — en skrivefeil eller et
    utenlandsk format er nok — og da kom det ingen advarsel i det hele
    tatt."""
    svar = _sladd(UGYLDIG)
    assert svar["kvalitet"]["ocr_brukt"] is False, "fixturen bruker ikke OCR"
    assert any("MERKET" in a for a in svar["advarsler"]), svar["advarsler"]


def test_funn_teller_fjernet_mistenkt_teller_misset():
    """De to feltene svarer på ULIKE spørsmål, og det må være synlig."""
    svar = _sladd(UGYLDIG)
    fjernet = {f["type"] for f in svar["funn"]}
    misset = {p["type"] for p in svar["mistenkt_usladdet"]}
    assert "telefon" in fjernet
    assert "organisasjonsnummer" in misset
    assert "organisasjonsnummer" not in fjernet
