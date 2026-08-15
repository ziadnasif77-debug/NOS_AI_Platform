"""
bytt_modell.py — bytt språkmodell trygt, og angre med én kommando.

    .pyruntime\\python.exe skript\\bytt_modell.py <sti-til-ny.gguf>
    .pyruntime\\python.exe skript\\bytt_modell.py --rull-tilbake
    .pyruntime\\python.exe skript\\bytt_modell.py --status
    .pyruntime\\python.exe skript\\bytt_modell.py --sjekk <sti-til-ny.gguf>

Det samme finnes i kontrollpanelet under fanen «Modeller», med knapper.

HVORFOR DETTE SKRIPTET FINNES
Serveren tar den nyeste .gguf-fila i modeller/borealis-gguf. Å bytte
modell er derfor «kopier inn en fil» — og det er nøyaktig problemet:
ingenting hindrer deg i å legge inn en modell som ikke får plass, som
er dårligere, eller som dikter tall. Utslagene er stille: et nativt
krasj uten traceback, en OCR som faller til CPU, eller svar som ser
riktige ut.

Skriptet gjør derfor hele runden, i rekkefølge, og STOPPER ved første
grunn til å ikke bytte:

    1. Finnes fila? Er den en ekte GGUF? (filsignatur, ikke filnavn)
    2. Får den plass — og blir det nok igjen til OCR? (R140)
    3. Treffer promptankrene fortsatt? (CLAUDE.md §4)
    4. Mål DAGENS modell på spørsmålskorpuset
    5. Bytt, og start serveren på nytt
    6. Mål den nye modellen på nøyaktig samme korpus
    7. Døm — og rull automatisk tilbake hvis den ikke er bedre

DOMMEN FALLER PÅ INTERVALLER, IKKE PÅ TO TALL
«87 riktige mot 82» er ikke en forbedring hvis korpuset har 45
spørsmål — det kan være ren tilfeldighet. Kvalitetsporten for
håndskriftmodellen lærte dette (R148): en fast margin flytter bare
terskelen for hvilken STØY som slipper gjennom. Derfor regnes et
95 %-konfidensintervall (bootstrap, fast frø) for begge modeller.
Overlapper de, kan modellene ikke skilles på dette korpuset, og da
promoteres ingenting.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from delt import maskinprofil, modellsjekk                      # noqa: E402

GGUF_MAPPE = ROT / "modeller" / "borealis-gguf"
FORRIGE_MAPPE = ROT / "modeller" / "borealis-forrige"
AVVIST_MAPPE = ROT / "modeller" / "borealis-avvist"
MAALINGER = ROT / "data" / "modellmaalinger"

BASE = os.environ.get("KORPUS_API", "http://127.0.0.1:8600")
KONTEKST = int(os.environ.get("BOREALIS_KONTEKST", "4096"))
# Borealis + OCR lastes ved oppstart; det tar tid på et fullt kort.
OPPSTARTSFRIST_S = int(os.environ.get("BYTT_MODELL_OPPSTART_S", "300"))
PYTHON = str(ROT / ".pyruntime" / "python.exe")
if not os.path.isfile(PYTHON):
    PYTHON = sys.executable


def _skriv(melding: str = "") -> None:
    print(melding, flush=True)


# ------------------------------------------------------------------ #
#  1–2. Filsjekk og VRAM                                              #
# ------------------------------------------------------------------ #

def er_gguf(sti: Path) -> bool:
    """Leser filens SIGNATUR, ikke navnet. En omdøpt .txt eller en
    halvlastet fil skal stoppes her — ikke av llama.cpp, som svarer med
    et nativt krasj uten traceback."""
    try:
        with open(sti, "rb") as f:
            return f.read(4) == b"GGUF"
    except OSError:
        return False


def avtrykk(sti: Path) -> str:
    """Størrelse + sha256 av første MiB — samme algoritme som
    delt/motoravtrykk.py og valider_modell.modell_avtrykk, så de tre
    kan sammenlignes med hverandre."""
    import hashlib
    try:
        h = hashlib.sha256()
        h.update(str(sti.stat().st_size).encode())
        with open(sti, "rb") as f:
            h.update(f.read(1024 * 1024))
        return h.hexdigest()[:16]
    except OSError:
        return "ukjent"


def totalt_vram_mb() -> float:
    """Kortets samlede VRAM i MiB (0.0 uten CUDA). Samme kilde som
    resten av systemet bruker: torch.cuda.mem_get_info."""
    try:
        import torch
        if not torch.cuda.is_available():
            return 0.0
        return torch.cuda.mem_get_info()[1] / (1024 * 1024)
    except Exception:
        return 0.0


def live_modell() -> Path:
    """GGUF-fila serveren ville valgt: nyeste .gguf, mmproj utelatt —
    identisk regel som _finn_gguf() i dokument_api.py."""
    try:
        kandidater = [p for p in GGUF_MAPPE.iterdir()
                      if p.suffix.lower() == ".gguf"
                      and not p.name.lower().startswith("mmproj")]
    except OSError:
        return None
    return max(kandidater, key=lambda p: p.stat().st_mtime) if kandidater else None


def forsjekk(kandidat: Path) -> dict:
    """Sjekk 1–3. Returnerer {holder, linjer, vram, ankre}."""
    linjer, holder = [], True

    if not kandidat.is_file():
        return {"holder": False,
                "linjer": [f"[FEIL] Fant ikke fila: {kandidat}"]}
    if not er_gguf(kandidat):
        return {"holder": False, "linjer": [
            f"[FEIL] {kandidat.name} er ikke en GGUF-fil (mangler "
            "GGUF-signaturen). Er nedlastingen fullført?"]}
    storrelse = kandidat.stat().st_size
    linjer.append(f"[OK]   Gyldig GGUF, {storrelse / (1024**3):.2f} GB, "
                  f"avtrykk {avtrykk(kandidat)}")

    vram = modellsjekk.vram_budsjett(storrelse, totalt_vram_mb(), KONTEKST)
    if vram["holder"] is None:
        linjer.append(f"[ADV]  {vram['forklaring']}")
    elif vram["holder"]:
        linjer.append(f"[OK]   {vram['forklaring']}")
    else:
        linjer.append(f"[FEIL] {vram['forklaring']}")
        # Å bare nekte er ikke godt nok for den som står med serveren og
        # ikke kan koden: si HVA som ville fått plass (R190).
        try:
            maks = maskinprofil.profil()["utledet"]["maks_modell_mb"]
            if maks:
                linjer.append(f"       Dette kortet tåler en modellfil på "
                              f"~{maks / 1024:.1f} GB med dagens kontekst "
                              f"({KONTEKST} tokens). Vil du kjøre en større "
                              "modell, må konteksten ned eller kortet opp.")
        except Exception:                                       # noqa: BLE001
            pass
        holder = False

    ankre = modellsjekk.sjekk_promptankre()
    if ankre["ok"]:
        linjer.append(f"[OK]   Promptankrene treffer "
                      f"({len(ankre['sjekket'])} av {len(ankre['sjekket'])} "
                      "blokker) — lange dokumenter klippes riktig")
    else:
        for a in ankre["avvik"]:
            linjer.append(f"[FEIL] Promptanker: {a}")
        holder = False

    return {"holder": holder, "linjer": linjer, "vram": vram, "ankre": ankre}


# ------------------------------------------------------------------ #
#  Server: stopp, start, vent                                         #
# ------------------------------------------------------------------ #

def _hjelp() -> dict:
    import urllib.request
    try:
        with urllib.request.urlopen(BASE + "/hjelp", timeout=10) as svar:
            return json.loads(svar.read().decode("utf-8"))
    except Exception:
        return {}


def server_svarer() -> bool:
    return bool(_hjelp())


def stopp_server() -> None:
    """Dreper det som holder API-porten. Samme framgangsmåte som
    kontrollpanelet bruker (netstat → taskkill)."""
    port = os.environ.get("DOKUMENT_API_PORT", "8600")
    uten_vindu = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        ut = subprocess.run(["netstat", "-ano"], capture_output=True,
                            text=True, timeout=20, creationflags=uten_vindu)
    except Exception:
        return
    pids = set()
    for linje in ut.stdout.splitlines():
        if f":{port}" in linje and "LISTENING" in linje.upper():
            deler = linje.split()
            if deler and deler[-1].isdigit():
                pids.add(deler[-1])
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/T", "/PID", pid],
                       capture_output=True, creationflags=uten_vindu)
    time.sleep(2)


def start_server_og_vent() -> dict:
    """Starter API-et og venter til Borealis melder «klar». Returnerer
    /hjelp-svaret, eller {} hvis fristen gikk ut."""
    uten_vindu = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    bat = ROT / "oppstart" / "start_api_med_vakthund.bat"
    skjult = ROT / "oppstart" / "_skjult.vbs"
    logg = ROT / "data" / "logger" / "oppstart_api.log"
    logg.parent.mkdir(parents=True, exist_ok=True)
    try:
        if skjult.is_file() and bat.is_file():
            subprocess.Popen(["wscript", "//nologo", str(skjult), str(bat),
                              str(logg)], cwd=str(ROT), creationflags=uten_vindu)
        else:
            subprocess.Popen([PYTHON, str(ROT / "skript" / "dokument_api.py")],
                             cwd=str(ROT), creationflags=uten_vindu)
    except OSError as exc:
        _skriv(f"[FEIL] Klarte ikke å starte serveren: {exc}")
        return {}

    frist = time.time() + OPPSTARTSFRIST_S
    sist = ""
    while time.time() < frist:
        data = _hjelp()
        status = data.get("borealis", "")
        if status and status != sist:
            _skriv(f"       Borealis: {status}")
            sist = status
        if status == "klar":
            return data
        if status == "feil":
            _skriv("[FEIL] Borealis kunne ikke lastes — se "
                   "data/logger/oppstart_api.log")
            return data
        time.sleep(3)
    _skriv(f"[FEIL] Serveren ble ikke klar innen {OPPSTARTSFRIST_S} s.")
    return {}


# ------------------------------------------------------------------ #
#  4/6. Måling                                                        #
# ------------------------------------------------------------------ #

def mal_modellen(merkelapp: str) -> dict:
    """Kjører spørsmålskorpuset mot den kjørende serveren.

    Linjene STRØMMES videre mens de kommer. En måling tar flere
    minutter, og et vindu som står stille i fem minutter ser ut som om
    noe har hengt seg — særlig for den som ikke kjenner systemet og
    ikke vet om den tør å avbryte."""
    _skriv(f"\n--- Måler {merkelapp} på spørsmålskorpuset ---")
    prosess = subprocess.Popen(
        [PYTHON, "-u", "-X", "utf8",
         str(ROT / "skript" / "kjor_sporsmaalskorpus.py"), "--json"],
        cwd=str(ROT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace")
    siste_json = None
    for linje in prosess.stdout:
        linje = linje.rstrip()
        if not linje:
            continue
        if linje.lstrip().startswith("{"):
            try:
                data = json.loads(linje)
                if isinstance(data, dict) and "utfall" in data:
                    siste_json = data
                    continue          # selve JSON-en er ikke for øyet
            except ValueError:
                pass
        _skriv("  " + linje)
    prosess.wait()
    if siste_json is None:
        _skriv("[FEIL] Fikk ikke et målbart resultat fra spørsmålskorpuset.")
        return {}
    _skriv(f"       {siste_json['bestatt']} av {siste_json['antall']} riktige "
           f"({siste_json['sekunder_per_svar']} s per svar)")
    return siste_json


def bootstrap_ki(utfall, runder: int = 2000, froe: int = 20260814):
    """95 %-konfidensintervall for andelen riktige svar.

    Fast frø med vilje — en port som gir ulik dom på samme inndata fra
    kjøring til kjøring er verre enn ingen port (samme begrunnelse som
    valider_modell.bootstrap_ki)."""
    import random
    if not utfall:
        return None
    tilfeldig = random.Random(froe)
    n = len(utfall)
    verdier = []
    for _ in range(runder):
        verdier.append(sum(utfall[tilfeldig.randrange(n)]
                           for _ in range(n)) / n)
    verdier.sort()
    return (round(verdier[int(0.025 * runder)], 4),
            round(verdier[min(runder - 1, int(0.975 * runder))], 4))


def overlapper(a, b) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def mcnemar(live, kandidat):
    """(rettet, ødelagt, p) for to kjøringer av SAMME korpus.

    R196: dette er den riktige testen her, og porten brukte feil.
    De to modellene svarer på nøyaktig de samme spørsmålene i samme
    rekkefølge — dataene er PARVISE. To uavhengige konfidensintervaller
    kaster den koblingen, og blir dermed langt for konservative: målt
    på et ekte tilfelle sa intervallene «ikke skillbar» om en endring
    som rettet 27 spørsmål og ødela 7 (p = 0,0008).

    Bare spørsmålene som ENDRET seg bærer informasjon om forskjellen —
    de 100 som var riktige begge ganger sier ingenting om hvilken
    modell som er best. Eksakt binomialtest, ingen tilnærming: korpuset
    er lite nok til at khikvadrat ikke er til å stole på."""
    from math import comb
    if not live or not kandidat or len(live) != len(kandidat):
        return 0, 0, None
    rettet = sum(1 for a, b in zip(live, kandidat) if a == 0 and b == 1)
    odelagt = sum(1 for a, b in zip(live, kandidat) if a == 1 and b == 0)
    n = rettet + odelagt
    if n == 0:
        return 0, 0, 1.0          # ingen forskjell i det hele tatt
    hale = sum(comb(n, k) for k in range(min(rettet, odelagt) + 1))
    return rettet, odelagt, min(1.0, 2.0 * hale / (2 ** n))


def dom(live: dict, kandidat: dict) -> dict:
    """Fire utfall — samme sett som kvalitetsporten for norhand."""
    if not live or not kandidat:
        return {"godkjent": False, "grunn": "ikke_maalt",
                "forklaring": "En av modellene ble ikke målt."}

    # KONTROLLGRUPPEN FØRST. Kode-svarte spørsmål skal være identiske
    # før og etter et bytte — endrer de seg, er rutingen brutt, og da
    # sier korpustallet ingenting om modellen.
    if kandidat.get("kode_bestatt") < live.get("kode_bestatt", 0):
        return {"godkjent": False, "grunn": "ruting_brutt",
                "forklaring": (
                    f"Spørsmål som besvares av KODEN falt fra "
                    f"{live['kode_bestatt']} til {kandidat['kode_bestatt']} "
                    "riktige. De går ikke gjennom modellen i det hele tatt, "
                    "så dette er en feil i rutingen — ikke i modellen. "
                    "Byttet stoppes.")}

    if not kandidat.get("determinisme", {}).get("ok", True):
        return {"godkjent": False, "grunn": "ikke_deterministisk",
                "forklaring": (
                    "Kandidaten ga ULIKE svar på samme spørsmål (R6). Da er "
                    "hvert avvik uetterprøvbart, og modellen kan ikke "
                    "brukes uansett hvor gode tallene ellers er.")}

    tallvakt = kandidat.get("tallvakt", {})
    if tallvakt.get("dom") == "hoy":
        return {"godkjent": False, "grunn": "dikter_tall",
                "forklaring": ("Tallvakten grep inn i uvanlig mange svar: "
                               + tallvakt.get("forklaring", ""))}

    ki_live = bootstrap_ki(live["utfall"])
    ki_kand = bootstrap_ki(kandidat["utfall"])
    andel_live = sum(live["utfall"]) / max(1, len(live["utfall"]))
    andel_kand = sum(kandidat["utfall"]) / max(1, len(kandidat["utfall"]))
    rettet, odelagt, p_verdi = mcnemar(live["utfall"], kandidat["utfall"])
    tall = (f"{andel_kand:.0%} mot {andel_live:.0%} — {rettet} spørsmål "
            f"rettet, {odelagt} ødelagt (McNemar p = {p_verdi:.4f}). "
            f"Konfidensintervall {ki_kand} mot {ki_live}")

    if p_verdi is None or p_verdi >= 0.05:
        return {"godkjent": False, "grunn": "ikke_skillbar",
                "ki_live": ki_live, "ki_kandidat": ki_kand,
                "p_verdi": p_verdi, "rettet": rettet, "odelagt": odelagt,
                "forklaring": (
                    f"Forskjellen er ikke målbar: {tall}. På dette korpuset "
                    "kan den være ren tilfeldighet, og da byttes ingenting.")}
    if rettet > odelagt:
        return {"godkjent": True, "grunn": "bedre",
                "ki_live": ki_live, "ki_kandidat": ki_kand,
                "p_verdi": p_verdi, "rettet": rettet, "odelagt": odelagt,
                "forklaring": f"Kandidaten er målbart bedre: {tall}."}
    return {"godkjent": False, "grunn": "daarligere",
            "ki_live": ki_live, "ki_kandidat": ki_kand,
            "p_verdi": p_verdi, "rettet": rettet, "odelagt": odelagt,
            "forklaring": f"Kandidaten er målbart DÅRLIGERE: {tall}."}


# ------------------------------------------------------------------ #
#  5. Selve byttet                                                    #
# ------------------------------------------------------------------ #

def _flytt_live_til(mappe: Path, fil: Path) -> None:
    mappe.mkdir(parents=True, exist_ok=True)
    for gammel in mappe.glob("*.gguf"):
        gammel.unlink()             # bare ÉN forrige — ellers vokser disken
    shutil.move(str(fil), str(mappe / fil.name))


def bytt_inn(kandidat: Path) -> Path:
    """Kandidat → live, nåværende live → borealis-forrige."""
    naa = live_modell()
    if naa is not None:
        _flytt_live_til(FORRIGE_MAPPE, naa)
        _skriv(f"       Forrige modell tatt vare på: "
               f"{FORRIGE_MAPPE.name}/{naa.name}")
    GGUF_MAPPE.mkdir(parents=True, exist_ok=True)
    maal = GGUF_MAPPE / kandidat.name
    # Kandidaten kan allerede LIGGE i modellmappa (en eldre .gguf som
    # ikke var nyest, og derfor ikke live). Da er kilde og mål samme
    # fil, og en kopi ville kastet SameFileError midt i byttet — etter
    # at forrige modell alt er flyttet vekk.
    if not (maal.exists() and maal.samefile(kandidat)):
        shutil.copy2(str(kandidat), str(maal))
    os.utime(maal, None)            # nyeste mtime = den serveren velger
    return maal


def rull_tilbake() -> bool:
    """Forrige modell tilbake i drift. Den utrullede tas vare på."""
    forrige = sorted(FORRIGE_MAPPE.glob("*.gguf")) if FORRIGE_MAPPE.is_dir() else []
    if not forrige:
        _skriv("Ingen forrige modell å rulle tilbake til "
               f"({FORRIGE_MAPPE} er tom).")
        return False
    naa = live_modell()
    if naa is not None:
        AVVIST_MAPPE.mkdir(parents=True, exist_ok=True)
        maal = AVVIST_MAPPE / naa.name
        if maal.exists():
            maal.unlink()
        shutil.move(str(naa), str(maal))
        _skriv(f"       Den utrullede modellen ligger i "
               f"{AVVIST_MAPPE.name}/{naa.name}")
    tilbake = forrige[0]
    GGUF_MAPPE.mkdir(parents=True, exist_ok=True)
    maal = GGUF_MAPPE / tilbake.name
    shutil.move(str(tilbake), str(maal))
    os.utime(maal, None)
    _skriv(f"Rullet tilbake til {tilbake.name}. Serveren må startes på nytt.")
    return True


def _lagre_maaling(merkelapp: str, data: dict) -> None:
    try:
        MAALINGER.mkdir(parents=True, exist_ok=True)
        stempel = datetime.now().strftime("%Y%m%d-%H%M%S")
        (MAALINGER / f"{stempel}-{merkelapp}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


# ------------------------------------------------------------------ #
#  Rapport                                                            #
# ------------------------------------------------------------------ #

def skriv_rapport(kandidatnavn: str, livenavn: str, live: dict,
                  kand: dict, vram: dict, avgjorelse: dict) -> None:
    _skriv("\n" + "=" * 64)
    _skriv(f"Kandidat: {kandidatnavn}")
    _skriv(f"Live:     {livenavn}")
    _skriv("")

    def rad(navn, k, l, enhet=""):
        _skriv(f"  {navn:<22} {k}{enhet:<6}   (live: {l}{enhet})")

    rad("Riktige svar:", f"{kand['bestatt']} / {kand['antall']}",
        f"{live['bestatt']} / {live['antall']}")
    rad("  av dette modellen:", f"{kand['modell_bestatt']} / {kand['modell_antall']}",
        f"{live['modell_bestatt']} / {live['modell_antall']}")
    rad("  av dette koden:", f"{kand['kode_bestatt']} / {kand['kode_antall']}",
        f"{live['kode_bestatt']} / {live['kode_antall']}")
    rad("Tallvakt stoppet:", kand["tallvakt"].get("stoppet"),
        live["tallvakt"].get("stoppet"))
    rad("Sekunder per svar:", kand["sekunder_per_svar"],
        live["sekunder_per_svar"])
    if vram and vram.get("behov_mb"):
        _skriv(f"  {'VRAM (anslag):':<22} {vram['behov_mb']} MB"
               f"      (igjen til OCR: {vram['igjen_til_ocr_mb']} MB, "
               f"grense {vram['ocr_krav_mb']})")
    _skriv("")
    if avgjorelse.get("ki_live"):
        _skriv(f"  Konfidensintervall  kandidat {avgjorelse['ki_kandidat']}  "
               f"live {avgjorelse['ki_live']}")
        _skriv("")
    merke = "GODKJENT" if avgjorelse["godkjent"] else "AVVIST"
    _skriv(f"RESULTAT:    {merke} ({avgjorelse['grunn']})")
    _skriv(f"BEGRUNNELSE: {avgjorelse['forklaring']}")
    _skriv("=" * 64)


def vis_status() -> int:
    # Maskinen først: alt under er utledet av den (R190).
    try:
        _skriv("")
        _skriv(maskinprofil.rapport())
    except Exception as exc:                                    # noqa: BLE001
        _skriv(f"(maskinprofil kunne ikke leses: {exc})")
    naa = live_modell()
    _skriv("\nSpråkmodell (Borealis)")
    _skriv(f"  Live:      {naa.name if naa else '(ingen .gguf funnet)'}")
    if naa:
        _skriv(f"             {naa.stat().st_size / (1024**3):.2f} GB, "
               f"avtrykk {avtrykk(naa)}")
    forrige = sorted(FORRIGE_MAPPE.glob("*.gguf")) if FORRIGE_MAPPE.is_dir() else []
    _skriv(f"  Forrige:   {forrige[0].name if forrige else '(ingen — ingenting å rulle tilbake til)'}")
    total = totalt_vram_mb()
    _skriv(f"  Kort:      {total:.0f} MB VRAM totalt" if total
           else "  Kort:      ingen CUDA funnet")
    data = _hjelp()
    if data:
        _skriv(f"  Server:    {data.get('borealis', '?')} "
               f"({data.get('borealis_modell') or 'ukjent fil'}, "
               f"motor {data.get('borealis_motor') or '?'})")
    else:
        _skriv("  Server:    svarer ikke (den må kjøre for å måle)")
    return 0


def main() -> int:
    argumenter = [a for a in sys.argv[1:] if a]
    if "--status" in argumenter:
        return vis_status()
    if "--rull-tilbake" in argumenter:
        return 0 if rull_tilbake() else 1

    bare_sjekk = "--sjekk" in argumenter
    stier = [a for a in argumenter if not a.startswith("--")]
    if len(stier) != 1:
        _skriv(__doc__)
        return 1
    kandidat = Path(stier[0]).expanduser()
    if not kandidat.is_absolute():
        kandidat = (Path.cwd() / kandidat).resolve()

    _skriv(f"\n=== Førflight-sjekk: {kandidat.name} ===")
    sjekk = forsjekk(kandidat)
    for linje in sjekk["linjer"]:
        _skriv("  " + linje)
    if not sjekk["holder"]:
        _skriv("\nAVBRUTT — byttet er ikke forsvarlig. Ingenting er endret.")
        return 1
    if bare_sjekk:
        _skriv("\nSjekk bestått. Kjør uten --sjekk for å måle og bytte.")
        return 0

    naa = live_modell()
    if naa is not None and avtrykk(naa) == avtrykk(kandidat):
        _skriv("\nKandidaten er BIT FOR BIT lik modellen som allerede kjører. "
               "Ingenting å bytte.")
        return 0

    if not server_svarer():
        _skriv("\n[FEIL] Serveren svarer ikke. Den må kjøre for at dagens "
               "modell skal kunne måles — start den først "
               "(oppstart\\start_api_med_vakthund.bat).")
        return 1

    live_maaling = mal_modellen("dagens modell")
    if not live_maaling:
        _skriv("\nAVBRUTT — uten en måling av dagens modell finnes det "
               "ingenting å sammenligne med. Ingenting er endret.")
        return 1
    _lagre_maaling("live", live_maaling)
    livenavn = naa.name if naa else "(ukjent)"

    _skriv("\n--- Bytter inn kandidaten ---")
    stopp_server()
    bytt_inn(kandidat)
    _skriv("       Starter serveren med den nye modellen ...")
    if not start_server_og_vent():
        _skriv("\n[FEIL] Serveren ble ikke klar med den nye modellen. "
               "Ruller tilbake.")
        stopp_server()
        rull_tilbake()
        start_server_og_vent()
        return 1

    kand_maaling = mal_modellen("kandidaten")
    _lagre_maaling("kandidat", kand_maaling)
    avgjorelse = dom(live_maaling, kand_maaling)
    skriv_rapport(kandidat.name, livenavn, live_maaling, kand_maaling,
                  sjekk.get("vram"), avgjorelse)

    if avgjorelse["godkjent"]:
        _skriv("\nModellen er byttet. Den kjører nå.")
        return 0
    _skriv("\nRuller tilbake til forrige modell ...")
    stopp_server()
    rull_tilbake()
    start_server_og_vent()
    _skriv("Forrige modell er tilbake i drift. Ingenting gikk tapt.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
