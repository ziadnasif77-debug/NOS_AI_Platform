"""Dokumenttype-styrte forventninger: hva SKAL finnes i et dokument av
en gitt type — og fant vi det? (R186)

Dette er typerutingen fra moderne Document AI-arkitektur («classification
first, then route to specialized extractors»), oversatt til husets
prinsipp: ingen egne uttrekksmodeller per type, men en LUKKET liste av
forventede felter per dokumenttype, sjekket mot det deterministiske
uttrekket som allerede er regnet ut. En faktura uten beløp er defekt
uansett hvor god OCR-en var — og det er et faktum kode kan bevise.

Tre garantier:
  * Feltvokabularet er lukket (`FELTDETEKTORER`): bare felter det
    deterministiske uttrekket kan påvise, kan forventes. En tastefeil i
    regelfila skaper aldri et felt resten av systemet ikke kjenner
    (samme prinsipp som skjemanummer_ytelse.txt).
  * Forventningene er KONSERVATIVE: bare det som er tilnærmet sikkert
    for typen står i standardtabellen. En overivrig forventning gir
    falske «mangler», og et felt som roper ulv slutter å bli lest.
  * Tomt forventningssett beviser ingenting: `[]` er en påstand (R128),
    og en rapport uten felter skal aldri brukes som bevis på at
    dokumentet er komplett.

Brukerens overstyring bor i `regler/dokumenttype_forventninger.txt` —
én linje per type, leses live (mtime), erstatter standarden for typen.
"""
import os

from delt.prompter import regelfil as _regelfil
from delt.tekstuttrekk import (DOKUMENTTYPE_TERM, gjett_dokumenttype,
                               strukturert_uttrekk)


def _liste(verdi) -> bool:
    return bool(verdi)


# Lukket feltvokabular: feltnavn → detektor over strukturert_uttrekk-
# svaret. Detektorene PÅVISER, de gjetter ikke — identifikatorene i
# strukturen er allerede sjekksumvalidert (mod11/mod10) der det finnes
# en sjekksum, så «funnet» betyr «funnet og gyldig».
FELTDETEKTORER = {
    "belop": lambda s: _liste(s.get("belop")),
    "dato": lambda s: _liste(s.get("datoer")),
    "periode": lambda s: _liste(s.get("perioder")),
    "fodselsnummer": lambda s: _liste(
        (s.get("identifikatorer") or {}).get("fodselsnummer")),
    "kontonummer": lambda s: _liste(
        (s.get("identifikatorer") or {}).get("kontonummer")),
    "organisasjonsnummer": lambda s: _liste(
        (s.get("identifikatorer") or {}).get("organisasjonsnummer")),
    "kid": lambda s: _liste(
        (s.get("identifikatorer") or {}).get("kid")),
    "saksnummer": lambda s: _liste(
        (s.get("identifikatorer") or {}).get("saksnummer")),
    "ytelse": lambda s: _liste((s.get("dokument") or {}).get("ytelse")),
    "telefon": lambda s: _liste((s.get("kontakt") or {}).get("telefoner")),
    "epost": lambda s: _liste((s.get("kontakt") or {}).get("eposter")),
    "adresse": lambda s: _liste(s.get("adresser")),
    "tittel": lambda s: _liste((s.get("dokument") or {}).get("tittel")),
}

# Standardforventninger per dokumenttype — bare det tilnærmet sikre.
# KID og kontonummer står IKKE på faktura med vilje: mange ekte
# fakturaer mangler dem, og en standard som roper «mangler» på friske
# dokumenter er verre enn ingen standard. Typer uten oppføring har
# ingen forventninger — da finnes det ingen rapport, og ingen påstand.
FORVENTNINGER = {
    "faktura": ("belop", "dato", "organisasjonsnummer"),
    "kvittering": ("belop", "dato"),
    "vedtak": ("fodselsnummer", "dato", "ytelse"),
    "soknad": ("fodselsnummer", "dato"),
    "legeerklaring": ("fodselsnummer", "dato"),
    "inntektsmelding": ("organisasjonsnummer", "fodselsnummer", "belop"),
    "sykmelding": ("fodselsnummer", "periode"),
    "klage": ("fodselsnummer", "dato"),
    "egenerklaring": ("fodselsnummer", "dato"),
    "meldekort": ("fodselsnummer", "periode"),
    "pensjonsbrev": ("fodselsnummer", "dato"),
}

# «typen = ingen» i regelfila: typen skal uttrykkelig IKKE ha
# forventninger — rapporten blir None, ikke et tomt (og dermed
# beviskraftløst) sett.
_INGEN = "ingen"

_BUFFER = None   # (mtime, tabell) — samme mønster som _skjema_ytelse


def _egne_forventninger() -> dict:
    """{dokumenttype: (felt, …) | None} fra regelfila — None betyr
    «uttrykkelig ingen». Leses på nytt bare når fila er endret. Ukjente
    dokumenttyper og ukjente feltnavn hoppes over: regelfila kan
    begrense og omfordele, aldri utvide vokabularet."""
    global _BUFFER
    sti = _regelfil("dokumenttype_forventninger.txt")
    try:
        stempel = os.path.getmtime(sti)
    except OSError:
        return {}
    if _BUFFER and _BUFFER[0] == stempel:
        return _BUFFER[1]
    tabell = {}
    try:
        # utf-8-sig av samme grunn som de andre regelfilene: Notepad
        # lagrer med BOM, og uten -sig slipper kommentarlinja forbi
        # «#»-filteret.
        with open(sti, encoding="utf-8-sig") as fil:
            for linje in fil:
                linje = linje.split("#", 1)[0].strip()
                if "=" not in linje:
                    continue
                kode, _, resten = linje.partition("=")
                kode = kode.strip().lower()
                if kode not in DOKUMENTTYPE_TERM:
                    continue
                if resten.strip().lower() == _INGEN:
                    tabell[kode] = None
                    continue
                felter = tuple(
                    f.strip().lower() for f in resten.split(",")
                    if f.strip().lower() in FELTDETEKTORER)
                if felter:
                    tabell[kode] = felter
    except OSError:
        return {}
    _BUFFER = (stempel, tabell)
    return tabell


def forventninger_for(dokumenttype) -> tuple | None:
    """Forventede felter for typen — regelfila vinner over standarden.
    None når typen er ukjent, uten forventninger, eller uttrykkelig
    satt til «ingen»."""
    if not dokumenttype:
        return None
    egne = _egne_forventninger()
    if dokumenttype in egne:
        return egne[dokumenttype]        # kan være None («ingen»)
    return FORVENTNINGER.get(dokumenttype)


def forventningsrapport(dokumenttype, struktur) -> dict | None:
    """{felter, funnet, mangler} for typen, målt mot det strukturerte
    uttrekket — eller None når typen ikke har forventninger. Rekkefølgen
    i listene følger forventningslisten, så rapporten er stabil."""
    forventet = forventninger_for(dokumenttype)
    if not forventet or not isinstance(struktur, dict):
        return None
    funnet = [f for f in forventet if FELTDETEKTORER[f](struktur)]
    return {
        "felter": list(forventet),
        "funnet": funnet,
        "mangler": [f for f in forventet if f not in funnet],
    }


def rapport_for_tekst(tekst: str) -> dict | None:
    """Klassifiser og mål i ett — for kallsteder som bare har teksten
    (gjennomgangsrutingens andre-sjekk, R187). Returnerer rapporten med
    `dokumenttype` i tillegg, eller None når typen er ukjent eller uten
    forventninger. NB: regner strukturert_uttrekk på nytt — brukes bare
    der DokumentKontekst ikke finnes, og kostnaden (regex over teksten)
    er avgrenset til dokumentene i mellombåndet."""
    if not (tekst or "").strip():
        return None
    dokumenttype = gjett_dokumenttype(tekst) or None
    rapport = forventningsrapport(dokumenttype,
                                  strukturert_uttrekk(tekst))
    if rapport is None:
        return None
    return {"dokumenttype": dokumenttype, **rapport}
