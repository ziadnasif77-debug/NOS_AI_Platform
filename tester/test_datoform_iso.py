"""Én datoform i svaret: ISO 8601.

Målt før fiksen, på ETT svar fra kjørende server: 55 verdier på norsk
form og 14 på ISO. Verre enn to formater — SAMME dato sto i begge:

    felter.dokumentdato.dato        "04.03.2026"
    dokumentprofil.dokument.dato    "2026-03-04"

    felter.dokumentdato.periode.fra "01.03.2026"
    dokumentprofil.dokument.spenn_fra "2026-03-01"

En RPA-robot som leser begge deler måtte skrive to parsere for det
samme begrepet, og — verre — kunne ikke vite hvilken den fikk uten en
tabell over hvilket felt som hadde hvilken form.

ISO er valgt fordi valget er målbart, ikke fordi det er penere:
  · det sorterer riktig som ren tekst («01.12.2025» < «02.01.2020» på
    norsk form — altså sortering på dagen, som er sortering på
    ingenting)
  · `date.fromisoformat` leser det uten egen parser
  · 03.04.2026 er tvetydig (3. april eller 4. mars, avhengig av leseren);
    ISO er det ikke.

Norsk form finnes fortsatt ETT sted: `til_norsk()`, som renderer når
utdataet skal inn i et norsk skjemafelt som selv sier «dd.mm.åååå».
Det er en renderer på kanten, ikke et felt i svaret (R110).
"""
import os
import re
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from delt.dokumentprofil import bygg_profil
from delt.tekstuttrekk import (finn_alle_datoer, finn_dato, finn_dokumentdato,
                               iso, klassifiser_datoer, sett_dato_roller,
                               strukturert_uttrekk, til_norsk)
from syntetiske_nummer import lag_fnr

NORSK_FORM = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}$")

DOK = """[Side 1 av 2]
NAV Arbeid og ytelser
Vedtak om sykepenger

Dokumentdato: 04.03.2026
Vedtaksdato: 01.03.2026
Mottatt: 28.02.2026

Opplysninger om: Ola Nordmann
Fodselsnummer: {FNR}
Saksnummer: 12345678

Perioden gjelder fra 01.01.2026 til 30.06.2026.
Utbetalingsdato: 25.03.2026
Ansatt fra 01.08.2019.
Soknad mottatt 2026-02-20.

[Side 2 av 2]
Klagefrist: seks uker fra 04.03.2026.
Neste kontroll: 1. september 2026.
""".replace("{FNR}", lag_fnr(0))


# Felt som med VILJE bærer originalteksten. De skal IKKE normaliseres:
# de er det eneste man kan kontrollere OCR mot (R110). Står det
# «28.02.2026» i dokumentet, skal det stå «28.02.2026» her — også når
# den normaliserte verdien ved siden av er ISO.
ORDRETTE = {"raatekst", "dato_original", "kontekst"}
# Fritekst til mennesker: begrunnelser og advarsler siterer dokumentet.
FRITEKST = {"begrunnelse", "advarsel", "merknad", "tekst", "beskrivelse",
            "forklaring"}


def _svaret():
    """Alt som bygger datofelter i et /dokument-svar, i én struktur."""
    datoer = sett_dato_roller(klassifiser_datoer(DOK))
    dokdato = finn_dokumentdato(datoer)
    struktur = strukturert_uttrekk(DOK)
    profil = bygg_profil(DOK, filnavn="p.txt", antall_sider=2,
                         datoer_detaljert=datoer, dokumentdato=dokdato,
                         struktur=struktur)
    return {"felter": {"dokumentdato": dokdato, "datoer_detaljert": datoer,
                       "datoer": finn_alle_datoer(DOK)},
            "struktur": struktur, "dokumentprofil": profil}


def _norske_verdier(node, sti="", ut=None, nokkel=None):
    if ut is None:
        ut = []
    if isinstance(node, dict):
        for k, v in node.items():
            _norske_verdier(v, f"{sti}/{k}", ut, k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _norske_verdier(v, f"{sti}/{i}", ut, nokkel)
    elif isinstance(node, str) and NORSK_FORM.match(node):
        if nokkel not in ORDRETTE and nokkel not in FRITEKST:
            ut.append((sti, node))
    return ut


# ------------------------------------------------------------------ #
#  1. Ingen norsk datoform i noen verdi                                #
# ------------------------------------------------------------------ #

def test_ingen_norsk_datoform_noe_sted_i_svaret():
    funn = _norske_verdier(_svaret())
    assert not funn, (
        "datoverdier på norsk form — svaret har igjen to grammatikker:\n"
        + "\n".join(f"  {s} = {v}" for s, v in funn))


def test_de_to_deltraerne_er_ENIGE_om_samme_dato():
    """Selve regresjonen: samme dato sto i to former i samme svar."""
    s = _svaret()
    assert (s["felter"]["dokumentdato"]["dato"]
            == s["dokumentprofil"]["dokument"]["dato"] == "2026-03-04")


def test_perioden_og_spennet_er_enige_paa_tvers_av_deltraerne():
    s = _svaret()
    spenn = s["felter"]["dokumentdato"]["periode"]
    dok = s["dokumentprofil"]["dokument"]
    assert spenn["fra"] == dok["spenn_fra"]
    assert spenn["til"] == dok["spenn_til"]


def test_datofelt_fra_saksfelter_har_samme_form_som_resten():
    """`arbeid.startdato` og `okonomi.utbetalingsdato` kom fra en annen
    kodevei (saksfelter.py) og måtte konverteres enkeltvis av en liste
    med feltnavn. Den lista måtte vedlikeholdes for hånd."""
    p = _svaret()["dokumentprofil"]
    assert p["arbeid"]["startdato"] == "2019-08-01"
    assert p["okonomi"]["utbetalingsdato"] == "2026-03-25"


# ------------------------------------------------------------------ #
#  2. Originalen er BEVART — normalisering skal ikke slette beviset    #
# ------------------------------------------------------------------ #

def test_raatekst_er_fortsatt_ordrett_norsk():
    """Uten dette ville «ingen norsk form noe sted» vært oppfylt av å
    normalisere BORT originalen — og da forsvant det eneste man kan
    kontrollere OCR mot."""
    d = _svaret()["felter"]["dokumentdato"]
    assert d["dato"] == "2026-03-04"
    assert d["raatekst"] == "04.03.2026"


def test_originalen_beholder_formen_dokumentet_faktisk_brukte():
    """Dokumentet skriver «2026-02-20» ett sted og «28.02.2026» et
    annet. Begge originaler skal stå slik de sto — `dato_original` er
    ikke en andre RENDERING av vår normaliserte verdi (R110)."""
    stempler = _svaret()["dokumentprofil"]["visuelt"]["stempel_datoer"]
    originaler = {s["dato_original"] for s in stempler}
    assert "28.02.2026" in originaler
    assert "2026-02-20" in originaler


# ------------------------------------------------------------------ #
#  3. Parseren leser fortsatt ALLE formene dokumenter bruker           #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("skrevet,forventet", [
    ("Vedtaksdato: 12.03.2021", "2021-03-12"),
    ("dato 3/1/2020 gjelder", "2020-01-03"),
    ("mottatt 2019-11-05 hos NAV", "2019-11-05"),
    ("Oslo, 12. januar 2020", "2020-01-12"),
    ("den 5 desember 1998", "1998-12-05"),
])
def test_alle_skrivemaater_gir_samme_ene_form(skrevet, forventet):
    assert finn_dato(skrevet) == forventet


@pytest.mark.parametrize("skrevet,forventet", [
    ("12 March 2024", "2024-03-12"),
    ("March 12, 2024", "2024-03-12"),
])
def test_engelske_maanedsnavn_gir_samme_ene_form(skrevet, forventet):
    """Engelske månedsnavn leses av `finn_alle_datoer`, ikke av
    `finn_dato` — en asymmetri som er eldre enn denne endringen, og som
    testes der den faktisk finnes så den ikke forveksles med en
    formatfeil."""
    assert finn_alle_datoer(skrevet) == [forventet]


# ------------------------------------------------------------------ #
#  4. Formen sorterer riktig — hele begrunnelsen for valget            #
# ------------------------------------------------------------------ #

def test_datoene_sorterer_riktig_som_ren_tekst():
    """På norsk form sorterer `sorted()` på DAGEN først. «01.12.2025»
    ville kommet før «02.01.2020» — altså sortering på ingenting."""
    tekst = "01.12.2025 og 02.01.2020 og 31.03.2022"
    assert sorted(finn_alle_datoer(tekst)) == ["2020-01-02", "2022-03-31",
                                               "2025-12-01"]


def test_formen_leses_av_standardbiblioteket():
    from datetime import date
    assert date.fromisoformat(finn_dato("Dato: 04.03.2026")) == date(2026, 3, 4)


# ------------------------------------------------------------------ #
#  5. Vakter mot at en andre form sniker seg inn igjen                 #
# ------------------------------------------------------------------ #

def test_datoformen_bygges_bare_ETT_sted():
    """Formen ble tidligere skrevet ut med f-streng fem steder. Da var
    det ingenting som hindret et sjette uttrekk i å velge en annen."""
    import inspect

    import delt.tekstuttrekk as tu
    kilde = inspect.getsource(tu)
    # linjer med kommentar strippet: en f-streng SITERT i en kommentar
    # er dokumentasjon, ikke kode
    kode = "\n".join(l.split("#")[0] for l in kilde.splitlines())
    byggere = re.findall(r'f"\{[dmy][^"]*:02d\}[.\-]', kode)
    assert len(byggere) <= 2, (
        f"datoformen bygges {len(byggere)} steder — den skal bygges av "
        f"`iso()` (og renderes av `til_norsk()`), ellers kan et nytt "
        f"uttrekk velge en annen form uten at noe sier fra")


def test_til_norsk_brukes_ikke_til_aa_bygge_svarfelter():
    """`til_norsk` er en renderer for skjemautfylling. Dukker den opp i
    en svarbygger, er den en R110-tvilling."""
    import inspect

    import dokument_api as api
    kilde = inspect.getsource(api)
    kode = [l for l in kilde.splitlines() if not l.strip().startswith("#")]
    bruk = [l.strip() for l in kode if "til_norsk(" in l]
    # de lovlige: importlinja, skjemaprompten, rensingen av skjemasvar,
    # og dato_tokens (som må kjenne begge renderinger for tallvakten)
    assert len(bruk) <= 4, (
        "til_norsk brukt flere steder enn de kjente rendererne:\n  "
        + "\n  ".join(bruk))


def test_parseren_godtar_ikke_norsk_form_som_inndata():
    """`_til_dato` er med vilje streng. Godtok den begge former, ville
    en gjenglemt norsk verdi regne riktig her og først vise seg ute i
    svaret — der den er dyrest å finne."""
    from delt.tekstuttrekk import _til_dato
    assert _til_dato("2026-03-04") is not None
    assert _til_dato("04.03.2026") is None


def test_iso_og_til_norsk_er_hverandres_motsatte():
    assert til_norsk(iso(4, 3, 2026)) == "04.03.2026"
    assert iso(4, 3, 2026) == "2026-03-04"
