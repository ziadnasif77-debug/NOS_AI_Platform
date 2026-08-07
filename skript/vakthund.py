"""
vakthund.py — holder dokument-API-et oppe, og SIER hvorfor det falt.

Bakgrunnen er målt, ikke antatt: over to døgn stoppet API-et gjentatte
ganger mens tunnelen, Label Studio og Prefect fortsatte å kjøre. Loggen
sluttet midt i en rekke `[GET] /hjelp → 200` — ingen traceback, ingen
oppføring i Windows' hendelseslogg, ingen «Stoppet.». Prosessen var bare
borte.

To problemer, og de er ulike:

  1. TJENESTEN ER NEDE. En RPA-robot som sender filer én etter én får
     502 fra tunnelen på hver eneste fil til noen oppdager det manuelt.

  2. VI VET IKKE HVORFOR. Ingenting fanget avslutningen. Derfor ga to
     døgn med krasj null informasjon å feilsøke på.

Vakthunden løser begge: den starter API-et, venter på det, og skriver
EXITKODEN til `data/logger/vakthund.log` med tidspunkt. Neste gang
prosessen dør har vi tallet — og på Windows sier tallet mye:

    3221225477  0xC0000005  minnetilgangsfeil (native krasj i
                            llama.cpp / CUDA / onnxruntime)
    3221225725  0xC00000FD  stakkoverflyt
             1              vanlig Python-feil (da står den i loggen)
             0              ryddig avslutning — noen stoppet den

HELSESJEKK, IKKE BARE «LEVER PROSESSEN»
En hengt prosess er like ubrukelig som en død. Derfor spørres `/hjelp`
med jevne mellomrom; svarer den ikke innen fristen flere ganger på rad,
regnes tjenesten som nede selv om prosessen finnes.

    python skript/vakthund.py              # kjør i forgrunnen
    python skript/vakthund.py --en-gang    # start, vent, rapporter, avslutt

Vakthunden eier prosessen den starter. Kjører API-et allerede (f.eks.
startet fra kontrollpanelet), legger den seg til å OVERVÅKE i stedet for
å starte en til — to servere på samme port ville gitt et vilkårlig av
dem svar.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGG = os.path.join(ROT, "data", "logger", "vakthund.log")
PORT = int(os.environ.get("DOKUMENT_API_PORT",
                          os.environ.get("UIPATH_API_PORT", "8600")))
HELSE_URL = f"http://127.0.0.1:{PORT}/hjelp"

# Oppstarten laster Borealis og OCR-modellene; helsesjekken må ikke
# konkludere «nede» mens det pågår.
OPPSTARTSFRIST_S = float(os.environ.get("VAKTHUND_OPPSTART_S", "180"))
SJEKK_INTERVALL_S = float(os.environ.get("VAKTHUND_INTERVALL_S", "20"))
SJEKK_FRIST_S = float(os.environ.get("VAKTHUND_SJEKK_S", "15"))
# Hvor mange sjekker på rad som må feile før vi starter på nytt. Én
# bom kan være en travel OCR-kjøring som holder tråden opptatt.
BOM_FOR_OMSTART = int(os.environ.get("VAKTHUND_BOM", "3"))
# Ubegrenset omstart av noe som krasjer med én gang er en løkke, ikke en
# vakthund. Ventetiden dobles, men aldri over taket.
PAUSE_START_S = 5.0
PAUSE_TAK_S = 300.0

# Windows-exitkoder som betyr «native krasj» — ingen Python-feil å finne
# i loggen, for tolken rakk aldri å reagere.
_KJENTE_KODER = {
    0: "ryddig avslutning (noen stoppet tjenesten)",
    1: "Python-feil — se oppstart_api.log for traceback",
    3221225477: "0xC0000005 MINNETILGANGSFEIL — native krasj "
                "(llama.cpp/CUDA/onnxruntime). Ingen Python-traceback "
                "finnes; se GPU-minne og BOREALIS_KONTEKST",
    3221225725: "0xC00000FD stakkoverflyt",
    3221226505: "0xC0000409 sikkerhetssjekk feilet (buffer overrun)",
    3221225786: "0xC000013A avbrutt med Ctrl+C",
    # TerminateProcess — noen (Oppgavebehandling, Stop-Process, et
    # opprydningsskript) drepte den. Ikke et krasj.
    4294967295: "0xFFFFFFFF DREPT UTENFRA — ikke et krasj. Se etter et "
                "skript eller en operatør som stopper prosessen",
}


def _skriv(melding: str) -> None:
    """Én linje til skjerm OG til vakthundloggen."""
    linje = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {melding}"
    print(linje, flush=True)
    try:
        os.makedirs(os.path.dirname(LOGG), exist_ok=True)
        with open(LOGG, "a", encoding="utf-8") as f:
            f.write(linje + "\n")
    except OSError:
        pass


def svarer() -> bool:
    """Svarer API-et på /hjelp? Endepunktet krever ikke nøkkel."""
    try:
        with urllib.request.urlopen(HELSE_URL, timeout=SJEKK_FRIST_S) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _tyd(kode) -> str:
    if kode is None:
        return "ukjent"
    kjent = _KJENTE_KODER.get(kode)
    if kjent:
        return f"{kode} — {kjent}"
    if kode > 0xC0000000:
        return f"{kode} (0x{kode:08X}) — native krasj, se Windows-kode"
    return str(kode)


MAKS_LOGG_MB = int(os.environ.get("VAKTHUND_MAKS_LOGG_MB", "10"))


def _roter_om_stor(sti: str):
    """Flytter loggen til «<navn>.1» når den er blitt stor.

    Loggen legges til og aldri over (se `start_api`), så uten rotasjon
    ville den vokst fritt. Ett arkiv er nok her: dette er en
    oppstarts- og krasjlogg, ikke et revisjonsspor — det siste
    krasjvinduet er det som betyr noe. Samme grense som `_skjult.vbs`,
    som roterer den samme fila på sin side av starten."""
    try:
        if os.path.getsize(sti) <= MAKS_LOGG_MB * 1024 * 1024:
            return
    except OSError:
        return                      # fila finnes ikke ennå
    arkiv = sti + ".1"
    try:
        if os.path.exists(arkiv):
            os.remove(arkiv)
        os.replace(sti, arkiv)
    except OSError as exc:
        # En åpen filhåndtak på Windows kan hindre flyttingen. Da er det
        # bedre å la loggen vokse enn å miste den.
        _skriv(f"kunne ikke rotere {os.path.basename(sti)}: {exc}")


def _barnets_utgang():
    """Hvor API-ets stdout/stderr skal.

    To skrivere på én fil er problemet vi nettopp fjernet ett sted og
    var i ferd med å innføre et annet. Startes vakthunden av
    `_skjult.vbs`, omdirigerer cmd allerede HELE .bat-en til
    `oppstart_api.log` — og på Windows er det håndtaket EKSKLUSIVT.
    Åpnet vakthunden samme fil selv, fikk den
    `PermissionError: [Errno 13]` og døde før den rakk å starte noe.
    Feilen ble fanget av nettopp den loggen som ikke lenger slettes.

    Regelen er derfor: er vår egen stdout allerede fanget (ikke et
    konsollvindu), lar vi barnet ARVE den. Én skriver, ett håndtak, og
    alt havner i samme fil uansett. Kjører vi i et konsoll, åpner vi
    loggfila selv — da er det ingen andre om beinet."""
    try:
        fanget = sys.stdout is not None and not sys.stdout.isatty()
    except Exception:
        fanget = False            # pythonw: ingen stdout i det hele tatt
    if fanget:
        return None               # arv vår egen — cmd eier fila

    logg_api = os.path.join(ROT, "data", "logger", "oppstart_api.log")
    os.makedirs(os.path.dirname(logg_api), exist_ok=True)
    _roter_om_stor(logg_api)
    # «a», ikke «w»: dette er fila vakthunden selv peker klienten til når
    # den skriver «se oppstart_api.log for traceback». Skrev vi over,
    # ville vi slettet nettopp det beviset vi ba noen lete etter.
    return open(logg_api, "a", encoding="utf-8", errors="replace")


def start_api() -> subprocess.Popen:
    """Starter serveren som EGEN prosess, med prosjektets egen Python."""
    py = os.path.join(ROT, ".pyruntime", "python.exe")
    if not os.path.exists(py):
        py = sys.executable
    miljo = {**os.environ, "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1"}
    miljo.setdefault("BOREALIS_KONTEKST", "4096")
    return subprocess.Popen(
        [py, os.path.join("skript", "dokument_api.py")],
        cwd=ROT, env=miljo, stdout=_barnets_utgang(),
        stderr=subprocess.STDOUT)


def vent_paa_oppstart(prosess, frist=OPPSTARTSFRIST_S) -> bool:
    """Venter til /hjelp svarer, eller til prosessen dør."""
    slutt = time.time() + frist
    while time.time() < slutt:
        if prosess is not None and prosess.poll() is not None:
            _skriv(f"DØDE UNDER OPPSTART — exitkode {_tyd(prosess.returncode)}")
            return False
        if svarer():
            return True
        time.sleep(2)
    _skriv(f"svarte ikke innen {frist:.0f} s etter start")
    return False


def hovedlokke(en_gang: bool = False) -> int:
    pause = PAUSE_START_S
    prosess = None

    if svarer():
        _skriv(f"API-et svarer allerede på port {PORT} — OVERVÅKER "
               f"(starter ikke en til; to servere på samme port ville "
               f"gitt et vilkårlig av dem svar)")
    else:
        _skriv(f"API-et svarer ikke på port {PORT} — starter det")
        prosess = start_api()
        if not vent_paa_oppstart(prosess):
            return 1
        _skriv("oppe og svarer")

    if en_gang:
        return 0

    bom = 0
    while True:
        time.sleep(SJEKK_INTERVALL_S)

        # Døde prosessen vi selv eier? Da HAR vi exitkoden — det er den
        # opplysningen som manglet i to døgn.
        if prosess is not None and prosess.poll() is not None:
            _skriv(f"PROSESSEN DØDE — exitkode {_tyd(prosess.returncode)}")
            prosess = None
            # Død prosess trenger ingen tålmodighet: her er det ingen
            # travel OCR-kjøring som kan svare om litt.
            bom = BOM_FOR_OMSTART - 1

        if svarer():
            if bom:
                _skriv("svarer igjen")
            bom = 0
            pause = PAUSE_START_S
            continue

        bom += 1
        _skriv(f"svarer ikke ({bom}/{BOM_FOR_OMSTART})")
        if bom < BOM_FOR_OMSTART:
            continue

        # Henger prosessen uten å være død, må den avlives før en ny kan
        # ta porten.
        if prosess is not None and prosess.poll() is None:
            _skriv("prosessen lever, men svarer ikke — avslutter den")
            try:
                prosess.terminate()
                prosess.wait(timeout=20)
            except Exception:
                try:
                    prosess.kill()
                except Exception:
                    pass
            _skriv(f"avsluttet — exitkode {_tyd(prosess.returncode)}")

        _skriv(f"starter på nytt om {pause:.0f} s")
        time.sleep(pause)
        prosess = start_api()
        if vent_paa_oppstart(prosess):
            _skriv("oppe igjen")
            bom = 0
            pause = PAUSE_START_S
        else:
            # Krasjer den med én gang, er hyppige forsøk en løkke, ikke
            # en vakthund. Vent lenger for hver gang.
            pause = min(pause * 2, PAUSE_TAK_S)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from delt import enkeltinstans

    # R141: `svarer()`-sjekken over er «sjekk, så handle» — ikke en lås.
    # Starter to vakthunder mens API-et er nede, ser BEGGE en død server
    # og starter hver sin. Og selv om de starter forskjøvet: dør API-et
    # senere, vil begge oppdage det og begge starte det på nytt.
    #
    # Vakthunden er dessuten det verste stedet å ha to av: den er
    # bygget for å RESTARTE, så to av dem kan restarte hverandres
    # servere i ring uten at loggen viser hvem som gjorde hva.
    _laas = enkeltinstans.ta("vakthund")
    if _laas is None and "--vent" in sys.argv:
        # R142: tjenesteveien VENTER i stedet for å avslutte.
        #
        # Oppgaveplanleggeren restarter bare en oppgave som avsluttet
        # med FEIL. Avslutter vi pent med 0 fordi panelet tilfeldigvis
        # rakk å starte sin vakthund først, regnes oppgaven som ferdig
        # — og lukker brukeren så panelet, står serveren uten tilsyn
        # til neste omstart. Da parkerer vi heller her og tar over i
        # det den andre forsvinner.
        _skriv("en vakthund kjører allerede — venter på tur "
               "(tjenesteveien avslutter ikke, den tar over)")
        while _laas is None:
            time.sleep(10)
            _laas = enkeltinstans.ta("vakthund")
        _skriv("den andre vakthunden er borte — overtar tilsynet")
    if _laas is None:
        _skriv("en vakthund kjører allerede — denne avslutter "
               "(to vakthunder ville startet hver sin server)")
        sys.exit(0)
    try:
        sys.exit(hovedlokke("--en-gang" in sys.argv))
    except KeyboardInterrupt:
        _skriv("vakthunden stoppet med Ctrl+C")
    finally:
        _laas.frigi()
