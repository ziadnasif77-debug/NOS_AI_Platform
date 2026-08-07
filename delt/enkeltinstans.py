"""Én instans om gangen — for prosesser der to er verre enn ingen.

Målt før denne fantes: to Python-servere kunne binde SAMME port
samtidig. Pythons `HTTPServer` setter `allow_reuse_address = 1`, og på
Windows betyr SO_REUSEADDR noe helt annet enn på Unix — der beskytter
den mot TIME_WAIT, her TILLATER den at en ny socket kaprer en port som
allerede er i bruk. To servere sto oppe, og forespørslene gikk til den
ene av dem uten at noe sa fra hvilken.

Konsekvensen er ikke bare forvirring: server nummer to laster Borealis
(~5,7 GB) på det samme 8 GB-kortet, og da har ingen av dem plass til
OCR. Kortet er prosjektets trangeste ressurs.

Låsen her er en NAVNGITT MUTEX i Windows-kjernen, ikke en låsefil.
Grunnen er den vanligste feilen med låsefiler: dør prosessen brått —
og det er nettopp det som skjer her, `0xC0000005` fra llama.cpp (R122)
— blir fila liggende, og neste oppstart nektes for alltid av en lås
ingen holder. En kjernemutex frigjøres av operativsystemet når
prosessen dør, uansett hvordan den døde.
"""
import os
import sys

# Windows-konstanter. GetLastError() etter CreateMutexW sier om vi
# LAGDE mutexen eller bare åpnet en andres.
_ALLEREDE = 183          # ERROR_ALREADY_EXISTS


def _er_windows() -> bool:
    return os.name == "nt"


class Laas:
    """Holder låsen så lenge objektet lever. Ta den med `ta`."""

    def __init__(self, navn, handtak=None, fil=None):
        self.navn = navn
        self._handtak = handtak
        self._fil = fil

    def frigi(self):
        if self._handtak is not None:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(self._handtak)
            self._handtak = None
        if self._fil is not None:
            try:
                self._fil.close()
            except OSError:
                pass
            self._fil = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.frigi()


def ta(navn: str):
    """Returnerer en `Laas` hvis vi fikk den, ellers None.

    `navn` skal være stabilt og entydig for prosjektet — to ulike
    nav-mapper på samme maskin skal IKKE stenge hverandre ute, så
    prosjektstien er en del av navnet.

    Låsen er GLOBAL på maskinen (Windows «Global\\»-navnerom brukes
    ikke — det krever rettigheter og trengs ikke; per-økt holder, siden
    tjenestene kjøres av samme bruker)."""
    if _er_windows():
        return _ta_windows(navn)
    return _ta_fil(navn)


def _prosjektnokkel() -> str:
    """Prosjektstien, gjort om til noe som kan stå i et mutexnavn.
    To kopier av nav-mappa er to ULIKE installasjoner."""
    rot = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return "".join(c if c.isalnum() else "_" for c in rot.lower())


def _ta_windows(navn: str):
    import ctypes
    fullt = f"nav_{_prosjektnokkel()}_{navn}"[:250]
    kernel32 = ctypes.windll.kernel32
    handtak = kernel32.CreateMutexW(None, False, fullt)
    if not handtak:
        # Klarte ikke å lage mutexen i det hele tatt. Da er det bedre å
        # SLIPPE gjennom enn å blokkere oppstart på noe vi ikke forstår:
        # låsen er et vern, ikke en funksjon brukeren ba om.
        return Laas(navn)
    if kernel32.GetLastError() == _ALLEREDE:
        kernel32.CloseHandle(handtak)
        return None
    return Laas(navn, handtak=handtak)


def _ta_fil(navn: str):
    """Fallback utenfor Windows: eksklusiv fil-lås via fcntl.

    Her er en låsefil trygg, for fcntl-låsen henger på filDESKRIPTOREN
    og slippes av kjernen når prosessen dør — akkurat som mutexen. Det
    er den løse «finnes fila?»-varianten som råtner."""
    import fcntl
    rot = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mappe = os.path.join(rot, "data", "laaser")
    os.makedirs(mappe, exist_ok=True)
    sti = os.path.join(mappe, f"{navn}.laas")
    fil = open(sti, "w")
    try:
        fcntl.flock(fil, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fil.close()
        return None
    return Laas(navn, fil=fil)


def krev(navn: str, hva: str, raad: str = "") -> "Laas":
    """Tar låsen, eller avslutter med en forklaring på stderr.

    For prosesser som ikke har noe fornuftig å gjøre uten den."""
    laas = ta(navn)
    if laas is None:
        melding = f"{hva} kjører allerede. Denne startes ikke."
        if raad:
            melding += f"\n{raad}"
        print(melding, file=sys.stderr)
        raise SystemExit(3)
    return laas
