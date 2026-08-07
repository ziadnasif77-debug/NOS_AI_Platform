"""`.env.example` er en INSTRUKS, og den må ikke lyve.

Fila kopieres til en ny server og blir det oppsettet tjenesten kjører
med. Da er en gal verdi der ikke dokumentasjonsgjeld — det er en
feilkonfigurasjon vi har skrevet ned og anbefalt.

Målt før fiksen sto:

    OCR_MINSTE_LEDIG_GPU_MB=800

Kodens standard er 2600, og kommentaren ved siden av den forklarer
hvorfor: «hevet fra 800. Med Borealis residerende (~5,7 GB av 8) ga 800
MiB grønt lys til EasyOCR på GPU-en — og llama.cpp sine compute-buffere
under neste inferens sprengte kortet → stille NATIV krasj (serveren bare
døde, ingen traceback)».

Eksempelfila anbefalte altså nøyaktig den verdien som ble hevet fordi
den felte tjenesten — og krasjet den gir er den som IKKE etterlater en
traceback, altså den dyreste å finne.

Og `.env` selv hadde 18 nøkler ingen kode leser. En død nøkkel er verre
enn ingen: den ser ut som en innstilling, så den blir justert, og
ingenting skjer.
"""
import io
import os
import re
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "skript"))

EKSEMPEL = os.path.join(ROT, ".env.example")
ENV = os.path.join(ROT, ".env")

# Navn som ser ut som miljøvariabler for et regexsøk, men er lokale
# variabler i .bat/.vbs eller testbrytere. De skal ikke kreves
# dokumentert i .env.example.
IKKE_KONFIG = {
    "C3", "H", "Y", "PY", "PYW", "KODE", "status", "fso", "sh",
    "PREFEKT_OK", "USERNAME", "USERDOMAIN", "UOPPDATER_FASIT",
    "NAV_SKJULT", "PYTHONNOUSERSITE", "PYTHONUTF8", "PYTHONIOENCODING",
}


def _nokler(sti):
    if not os.path.exists(sti):
        return {}
    ut = {}
    for linje in io.open(sti, encoding="utf-8"):
        s = linje.strip()
        if s and not s.startswith("#") and "=" in s:
            navn, verdi = s.split("=", 1)
            ut[navn.strip()] = verdi.strip()
    return ut


def _kildefiler():
    for mappe, _, filer in os.walk(ROT):
        if any(d in mappe for d in (".git", ".pyruntime", ".python",
                                    "__pycache__", ".venv-prefect",
                                    "offline_pakke")):
            continue
        for f in filer:
            if f.endswith((".py", ".bat", ".ps1", ".vbs", ".cmd")):
                yield os.path.join(mappe, f)


def _lest_i_koden():
    monstre = [
        re.compile(r'os\.environ\.get\(\s*["\']([A-Z0-9_]+)["\']'),
        re.compile(r'os\.getenv\(\s*["\']([A-Z0-9_]+)["\']'),
        re.compile(r'os\.environ\[\s*["\']([A-Z0-9_]+)["\']'),
        re.compile(r'os\.environ\.setdefault\(\s*["\']([A-Z0-9_]+)["\']'),
        re.compile(r"%([A-Z0-9_]+)%"),
        re.compile(r"\$env:([A-Za-z0-9_]+)"),
    ]
    funn = set()
    for sti in _kildefiler():
        try:
            tekst = io.open(sti, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in monstre:
            funn |= set(m.findall(tekst))
    return funn - IKKE_KONFIG


# Standardverdien slik koden selv skriver den:
#   os.environ.get("NAVN", "verdi")
_STANDARD = re.compile(
    r'os\.environ\.get\(\s*["\']([A-Z0-9_]+)["\']\s*,\s*["\']([^"\']*)["\']')


def _standarder_i_koden():
    ut = {}
    for sti in _kildefiler():
        if not sti.endswith(".py"):
            continue
        try:
            tekst = io.open(sti, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for navn, verdi in _STANDARD.findall(tekst):
            ut.setdefault(navn, set()).add(verdi)
    return ut


# ------------------------------------------------------------------ #
#  1. Eksempelfila må ikke anbefale noe annet enn koden gjør           #
# ------------------------------------------------------------------ #

def test_eksempelfila_motsier_ikke_kodens_egen_standard():
    """Selve vakten. Et avvik her betyr at den som kopierer mappa
    starter med et ANNET oppsett enn den som ikke gjør det — og det
    avviket er usynlig, fordi begge «virker» helt til de ikke gjør det.

    Er et avvik med VILJE, skal det stå i AVVIK under, med grunn."""
    AVVIK = {
        # navn: (verdi i eksempelfila, grunn)
    }
    eksempel = _nokler(EKSEMPEL)
    standarder = _standarder_i_koden()
    uenige = []
    for navn, verdi in eksempel.items():
        kode = standarder.get(navn)
        if not kode or not verdi:
            continue
        if verdi not in kode and navn not in AVVIK:
            uenige.append(f"{navn}: .env.example={verdi!r}, "
                          f"koden={sorted(kode)!r}")
    assert not uenige, (
        "«.env.example» anbefaler noe annet enn koden bruker:\n  "
        + "\n  ".join(uenige)
        + "\n\nEr det med vilje, før det opp i AVVIK med begrunnelse.")


def test_gpu_terskelen_er_den_MAALTE_ikke_den_som_krasjet():
    """Navngitt fordi den er den farligste enkeltverdien i fila: 800
    ga stille nativ krasj uten traceback."""
    verdi = _nokler(EKSEMPEL).get("OCR_MINSTE_LEDIG_GPU_MB")
    assert verdi is not None, "nøkkelen mangler helt"
    assert int(verdi) >= 2600, (
        f"OCR_MINSTE_LEDIG_GPU_MB={verdi} — 800 var verdien som felte "
        f"tjenesten. Senk den ikke uten å måle på nytt.")


def test_grunnen_staar_ved_verdien():
    """En terskel uten begrunnelse blir senket av den neste som synes
    OCR er treg. De andre risikoverdiene i fila har sin advarsel; denne
    hadde ingen."""
    tekst = io.open(EKSEMPEL, encoding="utf-8").read()
    plass = tekst.index("OCR_MINSTE_LEDIG_GPU_MB")
    foran = tekst[max(0, plass - 700):plass]
    assert "krasj" in foran.lower()


# ------------------------------------------------------------------ #
#  2. Ingen død konfigurasjon i noen av filene                         #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("fil", [".env.example", ".env"])
def test_ingen_nokkel_som_ingen_kode_leser(fil):
    """En død nøkkel er verre enn ingen: den ser ut som en innstilling,
    så den blir justert, og ingenting skjer. `.env` hadde 18."""
    sti = os.path.join(ROT, fil)
    if not os.path.exists(sti):
        pytest.skip(f"{fil} finnes ikke her")
    lest = _lest_i_koden()
    dode = sorted(n for n in _nokler(sti) if n not in lest)
    assert not dode, (
        f"{fil} har nøkler ingen kode leser: {dode}. Fjern dem, eller "
        f"koble dem til hvis de var ment å virke.")


def test_alle_hemmeligheter_er_TOMME_i_eksempelfila():
    """Eksempelfila er sporet i git. En nøkkel her ville ligget i
    historikken for alltid."""
    # ENDELSER, ikke delstrenger: «MAKS_SVAR_TOKENS» er et ANTALL, ikke
    # en hemmelighet, og en delstrengsjekk på «TOKEN» tok den.
    HEMMELIG = ("_NOKKEL", "_NOKLER", "_API_KEY", "_TOKEN", "_PASSORD",
                "_SECRET", "_PASSWORD")
    for navn, verdi in _nokler(EKSEMPEL).items():
        if navn.endswith(HEMMELIG):
            assert verdi == "", (
                f"{navn} har en verdi i .env.example — den skal være tom")


def test_eksempelfila_dekker_de_farlige_valgene():
    """Ikke alt trenger stå her — de fleste tunables har trygge
    standarder. Men de som KAN felle tjenesten skal være synlige og
    forklart, ikke bare finnes i koden."""
    eksempel = _nokler(EKSEMPEL)
    for navn in ("OCR_MINSTE_LEDIG_GPU_MB", "BOREALIS_KONTEKST",
                 "RATE_LIMIT_PER_MIN", "API_NOKKEL"):
        assert navn in eksempel, f"{navn} mangler i .env.example"


# ------------------------------------------------------------------ #
#  3. Det fila SIER om sikkerhet må stemme med det serveren GJØR       #
# ------------------------------------------------------------------ #

# Rutene som med vilje står åpne selv når API_NOKKEL er satt.
# /hjelp er helsesjekken vakthunden spør (R123). De tre andre utgjør
# dokumentasjonssiden: Swagger UI kjører i en nettleser og kan ikke
# sende headeren, så et nøkkelkrav der gjør dokumentasjonen ubrukelig.
# Ingen av dem returnerer dokumentinnhold.
AAPNE = ("/hjelp", "/openapi.json", "/dokumentasjon", "/statisk/")


def test_eksempelfila_lister_de_AAPNE_rutene_riktig():
    """Fila påsto «alle endepunkter unntatt /hjelp». Tre til er åpne.
    En sikkerhetspåstand som ikke stemmer er verre enn ingen — den
    leses som en garanti."""
    tekst = io.open(EKSEMPEL, encoding="utf-8").read()
    plass = tekst.index("API_NOKKEL=")
    foran = tekst[max(0, plass - 800):plass]
    for rute in ("/hjelp", "/openapi.json", "/dokumentasjon", "/statisk"):
        assert rute in foran, (
            f"«{rute}» er åpen, men står ikke i forklaringen ved "
            f"API_NOKKEL i .env.example")


def test_ingen_datarute_er_apen():
    """Speilet, og det som faktisk betyr noe: alt som bærer
    dokumentdata må gå gjennom nøkkelsjekken."""
    import inspect

    import dokument_api as api
    kilde = inspect.getsource(api.Handler)
    kode = "\n".join(l.split("#")[0] for l in kilde.splitlines())
    # POST-veien skal ALLTID innom _autorisert
    assert "_autorisert()" in kode
    for datarute in ("/dokument", "/jobb", "/spor", "/sladd", "/innsyn"):
        assert datarute not in AAPNE
