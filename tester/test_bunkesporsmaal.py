"""
Tester for bunkespørsmålene (delt/bunkesporsmaal.py, R229).

Fire korpusspørsmål handler ikke om hva som står i et dokument, men om
bunken som samling — og alle fire er TELLING. Modellen svarte «1 ULIKE
person» på en bunke med to, og «Arbeidsavkortning» (et ord som ikke
finnes) på spørsmålet om ytelser.

Testene holder på to ting:

  * tellingen er riktig, og bygger på fødselsnummer med kontrollsiffer
    — ikke på navn, som skrives på tre måter i den samme bunken
  * modulen svarer IKKE når den er i tvil, og tar ikke spørsmål som
    gjelder ett dokument eller en enkelt celle
"""
import sys

sys.path.insert(0, ".")

from delt import bunkesporsmaal                                 # noqa: E402
from tester.syntetiske_nummer import lag_fnr                    # noqa: E402

# To personer med gyldig kontrollsiffer. Numrene BYGGES her og står ikke
# i fila: et ellevesifret tall i kildekoden ser ut som et fødselsnummer
# uansett hvor syntetisk det er ment å være.
FNR_OLA = lag_fnr(0)
FNR_MARIT = lag_fnr(1)

BUNKE = "\n".join([
    "[Side 1 av 4]",
    "Vedtak om sykepenger",
    "OLA NORDMANN",
    f"Foedselsnummer: {FNR_OLA}",
    "[Side 2 av 4]",
    "Vedlegg 1 - Beregning av sykepenger",
    "[TABELL: Maaned, Dager, Bruttobeloep]",
    "Maaned: April 2026 | Dager: 21 | Bruttobeloep: 41 370",
    "Maaned: Mai 2026 | Dager: 20 | Bruttobeloep: 39 400",
    "Maaned: Juni 2026 | Dager: 22 | Bruttobeloep: 43 340",
    "Maaned: SUM | Dager: 63 | Bruttobeloep: 124 110",
    "Grunnlag",
    "[Side 3 av 4]",
    "Krav om tilbakebetaling - faktura",
    f"Foedselsnummer: {FNR_OLA}",
    "[Side 4 av 4]",
    "Klage paa vedtak om arbeidsavklaringspengar",
    f"Fraa: Marit Testperson, foedselsnummer {FNR_MARIT}",
])


def _svar(sporsmal, tekst=BUNKE):
    return bunkesporsmaal.svar(sporsmal, tekst)


# ------------------------------------------------------------------ #
#  De fire feilene som utløste modulen                                #
# ------------------------------------------------------------------ #

def test_antall_personer_telles_paa_fodselsnummer():
    """Modellen svarte «1 ULIKE person» på en bunke med to.

    Tellingen går på fødselsnummer, ikke navn: den samme personen står
    som «OLA NORDMANN», «Ola Nordmann Nor-Etternavn» og
    «NOR-ETTERNAVN, OLA» i én bunke, og et navnesøk ville talt tre."""
    r = _svar("Hvor mange ULIKE personer omtales i bunken?")
    assert r is not None
    assert r["svar"].startswith("2")
    assert r["grunnlag"] == "fodselsnummer"


def test_ulike_personer_i_vedtak_og_klage():
    """Vedtaket gjelder Ola, klagen er fra Marit. Modellen svarte «Ja,
    samme person» — og navnga til og med Ola."""
    r = _svar("Er det samme person som har faatt vedtaket og som klager?")
    assert r is not None
    assert r["svar"].lower().startswith("nei")


def test_samme_person_naar_numrene_er_like():
    """Garantien skal si JA like tydelig som NEI — ellers er den bare
    en mistanke."""
    lik = BUNKE.replace(FNR_MARIT, FNR_OLA)
    r = _svar("Er det samme person i vedtaket og klagen?", lik)
    assert r is not None and r["svar"].lower().startswith("ja")


def test_ytelsene_i_bunken_finnes_paa_begge_maalformer():
    """Klagen er skrevet på nynorsk og sier «arbeidsavklaringspengar».
    Ytelseslista var bokmål, så et nynorsk NAV-brev mistet ALLE
    ytelsene sine på én gang."""
    r = _svar("Hvilke to ytelser er omtalt i bunken?")
    assert r is not None
    lav = r["svar"].lower()
    assert "sykepenger" in lav
    assert "arbeidsavklaringspenger" in lav


def test_tabellrader_telles_uten_sumraden():
    ett = "\n".join(l for l in BUNKE.splitlines()
                    if not l.startswith("Klage"))
    r = bunkesporsmaal.svar("Hvor mange maaneder er med i tabellen?", ett)
    assert r is not None
    assert r["svar"] == "3", "sumraden skal ikke telles med"
    assert r["grunnlag"] == "tabellrader"


# ------------------------------------------------------------------ #
#  Den skal tie når den er i tvil                                     #
# ------------------------------------------------------------------ #

def test_verdisporsmaal_om_tabellen_tas_ikke():
    """«Hvor mange dager er SUMMEN i beregningstabellen?» ser nesten
    likedan ut som radtellingen, men svaret er en celle — 63, ikke 3.
    Tar modulen den, blir et riktig svar gjort galt."""
    assert _svar("Hvor mange dager er summen i beregningstabellen?") is None
    assert _svar("Hvor mange dager er det til sammen i tabellen?") is None


TO_TABELLER = BUNKE + "\n".join([
    "\n[Side 5 av 5]",
    "Inntektsmelding fra arbeidsgiver",
    "Inntekt siste tre maaneder",
    "[TABELL: Maaned, Grunnloenn]",
    "Maaned: Januar 2026 | Grunnloenn: 42 700",
    "Maaned: Februar 2026 | Grunnloenn: 42 700",
    "Maaned: Mars 2026 | Grunnloenn: 42 700",
])


def test_to_tabeller_uten_navn_i_sporsmaalet_gir_ingen_telling():
    """Bunken har to tabeller med kolonnen «Maaned» — beregningen og
    inntekten. Første utkast returnerte den første av dem, og svaret var
    riktig av FLAKS. En teller som velger vilkårlig mellom to tabeller,
    ser like sikker ut begge ganger. Sier ikke spørsmålet hvilken det
    gjelder, skal den tie."""
    assert bunkesporsmaal.svar(
        "Hvor mange maaneder er med i tabellen?", TO_TABELLER) is None


def test_tabellnavnet_i_sporsmaalet_avgjoer():
    """«beregningstabellen» peker på tabellen under overskriften
    «Beregning av sykepenger» — ikke på inntektstabellen, som også har
    en «Maaned»-kolonne. Da KAN den svare, og skal."""
    r = bunkesporsmaal.svar(
        "Hvor mange maaneder er med i beregningstabellen?", TO_TABELLER)
    assert r is not None and r["svar"] == "3"


def test_sporsmaal_om_ETT_dokument_tas_ikke():
    """«Hvilken ytelse gjelder klagen?» skal rutes til klagen, ikke
    besvares med hele bunkens ytelser."""
    assert _svar("Hvilken ytelse gjelder klagen?") is None
    assert _svar("Hvor mange personer staar i klagen?") is None


def test_ytelsesporsmaal_uten_bunkeord_tas_ikke():
    """«Hvilken ytelse gjelder tilbakebetalingskravet?» spør om ETT
    krav. Modulen svarte med bunkens to ytelser og BESTO fasiten, fordi
    den er et delstrengsøk — et riktig svar av feil grunn er en feil
    som venter."""
    assert _svar("Hvilken ytelse gjelder tilbakebetalingskravet?") is None


def test_samme_person_uten_to_dokumenter_tas_ikke():
    assert _svar("Er det samme person hele veien?") is None


def test_vanlige_sporsmaal_roeres_ikke():
    for spm in ("Hva er bruttobeloepet for juli 2026?",
                "Hvilken dato er vedtaket datert?",
                "Hvem har undertegnet vedtaket?",
                "Hvor mange sider har dokumentet?"):
        assert _svar(spm) is None, f"{spm!r} ble tatt"


def test_tom_inndata_er_trygg():
    assert bunkesporsmaal.svar("", BUNKE) is None
    assert bunkesporsmaal.svar("Hvor mange personer?", "") is None


def test_deterministisk():
    """R6: samme spørsmål og samme bunke gir samme svar."""
    spm = "Hvor mange ULIKE personer omtales i bunken?"
    forst = _svar(spm)["svar"]
    for _ in range(5):
        assert _svar(spm)["svar"] == forst
