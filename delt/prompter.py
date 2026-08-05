"""Laster promptene fra `regler/prompter.md` — den ENE kilden for alt
som sies til språkmodellen.

Hvorfor en fil og ikke strenger i koden: en regel som skal endres måtte
før dette letes opp blant tusenvis av kodelinjer, i to filer, i seks
ulike funksjoner — og ordlyden i `docs/regler_lokal_api.md` kunne si noe
annet enn det modellen faktisk fikk. Nå er det ett sted å lete, ett sted
å endre, og `tester/test_prompter_samlet.py` feiler hvis prompttekst
sniker seg tilbake inn i koden.

Fila leses på nytt når den er endret (mtime), slik at en ny regel virker
UMIDDELBART — samme prinsipp som `egne_regler.txt` og
`egne_etiketter.txt`. Mangler fila, feiler vi høylytt ved første kall:
en server som svarer uten reglene sine, svarer feil i stillhet.
"""
import os
import re
from string import Template

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPTER_STI = os.path.join(ROT, "regler", "prompter.md")

# [[navn]] … [[/navn]]. Navnet kan inneholde punktum (spor.uten_dokument).
_BLOKK = re.compile(
    r"^\[\[([a-zæøå0-9_.]+)\]\][ \t]*\r?\n(.*?)\r?\n\[\[/\1\]\][ \t]*$",
    re.DOTALL | re.MULTILINE | re.IGNORECASE)

_bufret = {"mtime": None, "blokker": {}}


def _les() -> dict:
    """Leser prompter.md på nytt hvis fila er endret siden sist.

    Går lesingen galt mens serveren kjører — typisk fordi noen står midt
    i å lagre fila i en editor — beholder vi den SISTE GYLDIGE utgaven og
    sier ifra i loggen. Alternativet ville vært at et tilfeldig spørsmål
    feilet fordi noen trykket Ctrl+S i samme sekund. Har vi ingen gyldig
    utgave (fila manglet allerede ved oppstart), feiler vi høylytt: en
    server som svarer uten reglene sine, svarer feil i stillhet."""
    def _gi_opp(melding: str, feil: Exception | None = None):
        if _bufret["blokker"]:
            print(f"  prompter: {melding} — bruker forrige gyldige utgave")
            return _bufret["blokker"]
        raise RuntimeError(melding) from feil

    try:
        mtime = os.path.getmtime(PROMPTER_STI)
    except OSError as feil:
        return _gi_opp(
            f"Finner ikke regelfila {PROMPTER_STI} — uten den vet ikke "
            f"modellen hvilke regler den skal følge, og svarene kan ikke "
            f"stoles på. ({feil})", feil)
    if _bufret["mtime"] == mtime:
        return _bufret["blokker"]
    try:
        with open(PROMPTER_STI, encoding="utf-8-sig") as f:
            raa = f.read()
    except (OSError, UnicodeDecodeError) as feil:
        return _gi_opp(f"Kunne ikke lese {PROMPTER_STI}: {feil}", feil)
    blokker = {navn: tekst for navn, tekst in _BLOKK.findall(raa)}
    if not blokker:
        return _gi_opp(
            f"{PROMPTER_STI} inneholder ingen [[blokker]] — er markørene "
            f"skrevet feil? En blokk åpnes med [[navn]] og lukkes med "
            f"[[/navn]], begge alene på hver sin linje.")
    _bufret.update(mtime=mtime, blokker=blokker)
    return blokker


def blokknavn() -> set:
    """Navnene på alle blokker i fila — brukes av vakttesten."""
    return set(_les())


def hent(navn: str, **felter) -> str:
    """Prompten `navn` med plassholderne fylt ut.

    Mangler en blokk eller et felt, sier vi det rett ut med navnet på
    det som mangler — en halvfylt prompt med «$dokument» stående igjen
    ville gitt et svar som SÅ riktig ut."""
    blokker = _les()
    if navn not in blokker:
        raise KeyError(
            f"Ingen prompt som heter «{navn}» i {PROMPTER_STI}. "
            f"Blokker som finnes: {', '.join(sorted(blokker))}")
    try:
        return Template(blokker[navn]).substitute(**felter)
    except KeyError as feil:
        raise KeyError(
            f"Prompten «{navn}» venter feltet {feil} som ikke ble sendt "
            f"med. Kallstedet og blokka er ute av takt.") from feil


def avsnitt(navn: str, **felter) -> str:
    """Som hent(), men med linjeskift bak — for biter som limes inn i en
    annen prompt (`${ocr_merknad}` og `${usikre_blokk}`). Kalleren tar
    et tomt avsnitt ved å sende "" i stedet, og da blir det ingenting
    igjen i prompten."""
    return hent(navn, **felter) + "\n"


def versjon() -> str:
    """Promptversjonen (R39) — følger med i alle API-svar, så et svar
    kan spores tilbake til nøyaktig den ordlyden som ga det."""
    return hent("versjon").strip()


def regelfil(navn: str) -> str:
    """Stien til en av brukerens egne regelfiler (`egne_regler.txt`,
    `egne_etiketter.txt`). De bor i `regler/` sammen med prompter.md, så
    alt som styrer svarene ligger i ÉN mappe.

    Tilbakefall til prosjektroten: en kopi av nav-mappa som ble tatt før
    flyttingen har filene liggende der, og den skal ikke miste reglene
    sine bare fordi den ble kopiert på feil dag."""
    ny = os.path.join(ROT, "regler", navn)
    if os.path.exists(ny):
        return ny
    gammel = os.path.join(ROT, navn)
    return gammel if os.path.exists(gammel) else ny
