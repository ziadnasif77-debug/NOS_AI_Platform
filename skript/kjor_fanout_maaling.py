"""
Lokal fan-out: tåler ÉN maskin kravet, eller trengs det en kø? (§24.1)

    .pyruntime\\python.exe skript\\kjor_fanout_maaling.py
    .pyruntime\\python.exe skript\\kjor_fanout_maaling.py --sider 40 --grader 2,4,6

Implementeringsspesifikasjonen slipper ikke Phase 2 (RabbitMQ/Redis,
flere noder) løs før lokal fan-out etter optimalisering IKKE lenger
tilfredsstiller målkravene. Den porten kan bare åpnes av en måling, og
målingen fantes ikke: i dag leses sidene ÉN OM GANGEN i jobbarbeideren.

HVA ÉN «PAGE TASK» ER HER
Rendre siden + `ocr_side` — nøyaktig det arbeidet en fan-out ville delt
på. Riggen kjører samme bunke sider i flere moduser og sammenligner:

  sekvensiell         én side om gangen (dagens jobbarbeider)
  traader-N           N tråder, gjennom `ocr_side` som den er
  traader-uten-laas-N N tråder, UTENOM modullåsen — en sonde
  prosesser-N         N prosesser, hver med hele maskinen
  prosesser-pinnet-N  N prosesser som DELER maskinen (12/N tråder hver)

SONDEN ER DET ØKONOMISKE SPØRSMÅLET
`ocr_side` holder en modulglobal lås (`_las`) rundt HELE siden. Er det
låsen og ikke maskinen som er taket, koster fiksen noen få linjer i
stedet for et prosessmaskineri. Sonden svarer på det UTEN å gjøre
inngrepet først og måle etterpå. Er svaret «ingenting», er låsen
uskyldig og produksjonskoden får stå.

DETERMINISME AVGJØR FØR FART
Hver modus må gi BIT-IDENTISK tekst per side, ellers er farten verdiløs
(R6). En modus som avviker forkastes uansett hvor rask den var.

HVA MÅLINGEN IKKE DEKKER — SAGT HØYT
Håndskriftmodellen er slått AV (`MAKS_NORHAND_PER_SIDE=0`), så dette er
RapidOCR-veien alene. Grunnen er at den er veien: i 500-sidersmålingen
sto RapidOCR for 13 450 av 13 768 regioner — 97,7 %. De siste 2,3 % går
til norhand på GPU-en, og de serialiseres uansett av sin egen GPU-lås,
så de påvirkes ikke av fan-out.

Første forsøk lot norhand kjøre på CPU i stedet. Det virket uskyldig,
men flyttet norhand fra ~3 % til ~34 % av tiden — altså målte riggen en
helt annen arbeidsmiks enn produksjonen har, og kalte det fan-out.

MÅLINGEN SJEKKER SEG SELV
Den sekvensielle grunnlinjen kjøres om igjen til SLUTT. Driver de to fra
hverandre, var maskinen ikke i ro under kjøringen, og hele runden er
ugyldig — ikke «litt usikker». Den kontrollen finnes fordi den manglet:
et rekursivt søk startet ved siden av den første kjøringen ga
grunnlinjen 2,9 av 12 kjerner i stedet for 5,4, og hver eneste speedup
i tabellen ble målt mot en grunnlinje som var sultet.
"""
import argparse
import json
import os
import sys
import threading
import time

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "skript"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                               # noqa: BLE001
    pass

KILDE = os.path.join(ROT, "data", "korpus", "syntetisk_bunke_skann.pdf")

# Betingelsene målingen kjører under. Settes i BÅDE foreldre og barn.
# `rapid` er ikke et valg for anledningen — det er policyen maskinen
# faktisk froser med Borealis på kortet (R199).
BETINGELSER = {
    "OCR_MOTOR": "rapid",
    "MAKS_NORHAND_PER_SIDE": "0",
}

# Hvor mye de to grunnlinjene får drive fra hverandre før runden er ugyldig.
MAKS_DRIFT = 0.15

# ETT dokument PER TRÅD. Et fitz.Document er ikke trådsikkert: rendrer to
# tråder hver sin side av samme objekt, deler de intern tilstand i MuPDF.
# Det er ikke et teoretisk problem — det er nettopp en slik deling en
# fan-out ville innført, og en rigg som krasjer på den ville målt sin
# egen feil i stedet for maskinens tak.
_lokal = threading.local()


# ------------------------------------------------------------------ #
#  Én Page Task — nøyaktig det jobbarbeideren gjør per side           #
# ------------------------------------------------------------------ #

def _dokument():
    d = getattr(_lokal, "pdf", None)
    if d is None:
        import fitz
        d = _lokal.pdf = fitz.open(KILDE)
    return d


def _bilde(nr: int):
    import numpy as np
    from dokument_api import ocr_skala

    doc = _dokument()
    side = doc[nr % doc.page_count]
    pix = side.get_pixmap(matrix=ocr_skala(doc, side))
    bilde = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n)
    return bilde[:, :, :3] if pix.n == 4 else bilde


def les_side(nr: int) -> tuple:
    """Page Task slik jobbarbeideren gjør den i dag."""
    from delt.region_ocr import ocr_side
    return nr, ocr_side(_bilde(nr))["tekst"]


def les_side_uten_laas(nr: int) -> tuple:
    """Samme Page Task, men UTENOM modullåsen i `ocr_side`.

    En SONDE, ikke et forslag: den svarer på hva det ville gitt å gjøre
    låsen smalere, uten å gjøre det først og måle etterpå.

    Trygt her fordi `_varm_opp()` har lastet motoren på forhånd — det er
    MODELLASTINGEN låsen beskytter — og fordi denne målingen kjører
    RapidOCR på CPU, altså uten GPU i bildet i det hele tatt."""
    from delt import region_ocr
    return nr, region_ocr._ocr_side_intern(_bilde(nr))["tekst"]


def _varm_opp() -> None:
    """Last motoren FØR målingen. Havner lastingen inne i den målte
    tiden, måler man oppstart og kaller det gjennomstrømning."""
    les_side(0)


def _barn_start() -> None:
    for k, v in BETINGELSER.items():
        os.environ[k] = v
    sys.path.insert(0, ROT)
    sys.path.insert(0, os.path.join(ROT, "skript"))
    _varm_opp()


# ------------------------------------------------------------------ #
#  Modusene                                                           #
# ------------------------------------------------------------------ #

def kjor_sekvensielt(sider: int) -> dict:
    _varm_opp()
    cpu0, t0 = time.process_time(), time.perf_counter()
    tekster = dict(les_side(n) for n in range(sider))
    brukt = time.perf_counter() - t0
    return {"tid": brukt, "tekster": tekster,
            "kjerner_brukt": (time.process_time() - cpu0) / max(brukt, 1e-9)}


def kjor_traader(sider: int, arbeidere: int, uten_laas: bool = False) -> dict:
    from concurrent.futures import ThreadPoolExecutor
    _varm_opp()
    oppgave = les_side_uten_laas if uten_laas else les_side
    cpu0, t0 = time.process_time(), time.perf_counter()
    with ThreadPoolExecutor(max_workers=arbeidere) as pool:
        tekster = dict(pool.map(oppgave, range(sider)))
    brukt = time.perf_counter() - t0
    return {"tid": brukt, "tekster": tekster,
            "kjerner_brukt": (time.process_time() - cpu0) / max(brukt, 1e-9)}


def kjor_prosesser(sider: int, arbeidere: int, traader=None) -> dict:
    """`traader` = hvor mange CPU-tråder HVER leser får.

    None lar hver leser ta hele maskinen — det naive oppsettet, og det
    som gjør at N lesere starter N×12 tråder på 12 kjerner. Et tall
    deler maskinen mellom dem i stedet. Miljøvariabelen settes i
    FORELDEREN: på Windows arves miljøet ved prosessoppstart, og
    `OCR_TRAADER_PER_MOTOR` leses når barnet importerer region_ocr."""
    from concurrent.futures import ProcessPoolExecutor
    if traader:
        os.environ["OCR_TRAADER_PER_MOTOR"] = str(traader)
    else:
        os.environ.pop("OCR_TRAADER_PER_MOTOR", None)
    t_start = time.perf_counter()
    with ProcessPoolExecutor(max_workers=arbeidere,
                             initializer=_barn_start) as pool:
        # Første kall tvinger oppstart+oppvarming av alle barna. Den
        # tiden holdes utenfor: vi måler drift, ikke kaldstart.
        list(pool.map(les_side, range(arbeidere)))
        oppstart = time.perf_counter() - t_start
        t0 = time.perf_counter()
        tekster = dict(pool.map(les_side, range(sider)))
        brukt = time.perf_counter() - t0
    return {"tid": brukt, "tekster": tekster, "oppstart": oppstart}


# ------------------------------------------------------------------ #
#  Rapport                                                            #
# ------------------------------------------------------------------ #

def _avvik(fasit: dict, tekster: dict) -> list:
    """Hvilke sider ble LEST ANNERLEDES enn i den sekvensielle kjøringen?"""
    return sorted(n for n, t in tekster.items()
                  if (fasit.get(n) or "") != (t or ""))


def main() -> int:
    p = argparse.ArgumentParser(description="Lokal fan-out-måling (§24.1)")
    p.add_argument("--sider", type=int, default=40)
    p.add_argument("--grader", default="2,4,6",
                   help="antall arbeidere å prøve, kommaseparert")
    p.add_argument("--hopp-prosesser", action="store_true")
    p.add_argument("--ut", default=os.path.join(
        ROT, "data", "maalinger", "fanout.json"))
    args = p.parse_args()

    if not os.path.isfile(KILDE):
        raise SystemExit(f"Fant ikke kilden: {KILDE}")
    grader = [int(g) for g in args.grader.split(",") if g.strip()]

    import multiprocessing
    kjerner = multiprocessing.cpu_count()
    for k, v in BETINGELSER.items():
        os.environ[k] = v

    print(f"  Sider per kjøring: {args.sider}   Logiske kjerner: {kjerner}")
    print(f"  Betingelser: {BETINGELSER}")
    print(f"  Kilde: {os.path.relpath(KILDE, ROT)}\n")

    resultater = []

    print("  [sekvensiell] ...", flush=True)
    grunn = kjor_sekvensielt(args.sider)
    fasit = grunn["tekster"]
    grunnfart = args.sider / grunn["tid"]
    resultater.append({"modus": "sekvensiell", "arbeidere": 1,
                       "tid": grunn["tid"], "fart": grunnfart,
                       "speedup": 1.0, "avvik": [],
                       "kjerner_brukt": grunn["kjerner_brukt"]})
    print(f"      {grunn['tid']:.1f} s  →  {grunnfart:.2f} sider/s   "
          f"(bruker {grunn['kjerner_brukt']:.1f} av {kjerner} kjerner)\n")

    def foer(navn, r, ekstra=None):
        fart = args.sider / r["tid"]
        rad = {"modus": navn[0], "arbeidere": navn[1],
               "tid": r["tid"], "fart": fart, "speedup": fart / grunnfart,
               "avvik": _avvik(fasit, r["tekster"])}
        rad.update(ekstra or {})
        if "kjerner_brukt" in r:
            rad["kjerner_brukt"] = r["kjerner_brukt"]
        if "oppstart" in r:
            rad["oppstart"] = r["oppstart"]
        resultater.append(rad)
        kjerne = (f"   (bruker {r['kjerner_brukt']:.1f} av {kjerner} kjerner)"
                  if "kjerner_brukt" in r else
                  f"   kaldstart {r.get('oppstart', 0):.0f} s")
        print(f"      {r['tid']:.1f} s  →  {fart:.2f} sider/s   "
              f"({fart / grunnfart:.2f}×){kjerne}\n")

    for n in grader:
        for merke, uten_laas in (("traader", False),
                                 ("traader-uten-laas", True)):
            print(f"  [{merke}-{n}] ...", flush=True)
            foer((merke, n), kjor_traader(args.sider, n, uten_laas))

    if not args.hopp_prosesser:
        for n in grader:
            # Fri: hver leser tar hele maskinen (det naive oppsettet).
            # Pinnet: maskinen DELES, så N lesere til sammen bruker
            # kjernene én gang i stedet for N ganger.
            for merke, traader in (("prosesser", None),
                                   ("prosesser-pinnet", max(1, kjerner // n))):
                merking = f" ({traader} tr/leser)" if traader else ""
                print(f"  [{merke}-{n}{merking}] ...", flush=True)
                try:
                    r = kjor_prosesser(args.sider, n, traader)
                except Exception as exc:                        # noqa: BLE001
                    print(f"      FEILET: {exc}\n")
                    resultater.append({"modus": merke, "arbeidere": n,
                                       "feil": str(exc)[:200]})
                    continue
                foer((merke, n), r, {"traader_per_leser": traader})

    # --- Var maskinen i ro hele veien? ------------------------------
    print("  [sekvensiell-kontroll] ...", flush=True)
    kontroll = kjor_sekvensielt(args.sider)
    kontrollfart = args.sider / kontroll["tid"]
    drift = abs(kontrollfart - grunnfart) / grunnfart
    print(f"      {kontroll['tid']:.1f} s  →  {kontrollfart:.2f} sider/s   "
          f"(drift {drift * 100:.1f} %)\n")

    print("=" * 74)
    print(f"  {'modus':<24}{'tid':>8}{'sider/s':>10}{'speedup':>10}"
          f"{'tekstavvik':>13}")
    print("  " + "-" * 63)
    for r in resultater:
        navn = (r["modus"] if r["modus"] == "sekvensiell"
                else f"{r['modus']}-{r['arbeidere']}")
        if "feil" in r:
            print(f"  {navn:<24}{'FEILET':>8}")
            continue
        avvik = r.get("avvik") or []
        dom = "identisk" if not avvik else f"{len(avvik)} sider!"
        print(f"  {navn:<24}{r['tid']:>7.1f}s{r['fart']:>10.2f}"
              f"{r['speedup']:>9.2f}×{dom:>13}")
    print("=" * 74)

    gyldig = drift <= MAKS_DRIFT
    if not gyldig:
        print(f"\n  RUNDEN ER UGYLDIG: grunnlinjen driftet {drift * 100:.1f} % "
              f"(tåler {MAKS_DRIFT * 100:.0f} %). Maskinen var ikke i ro — "
              "kjør på nytt uten annet arbeid på den.")
    else:
        gyldige = [r for r in resultater
                   if "feil" not in r and not r.get("avvik")]
        best = max(gyldige, key=lambda r: r["fart"]) if gyldige else None
        if best:
            navn = (best["modus"] if best["modus"] == "sekvensiell"
                    else f"{best['modus']}-{best['arbeidere']}")
            print(f"\n  BESTE DETERMINISTISKE MODUS: {navn} — "
                  f"{best['fart']:.2f} sider/s ({best['speedup']:.2f}×)")
    for r in resultater:
        if r.get("avvik"):
            print(f"  FORKASTET {r['modus']}-{r['arbeidere']}: leste "
                  f"{len(r['avvik'])} sider annerledes enn sekvensielt — "
                  "fart som endrer svaret er ingen fart (R6).")

    os.makedirs(os.path.dirname(args.ut), exist_ok=True)
    with open(args.ut, "w", encoding="utf-8") as f:
        json.dump({"sider": args.sider, "kjerner": kjerner,
                   "betingelser": BETINGELSER, "gyldig": gyldig,
                   "grunnlinjedrift": drift,
                   "resultater": [{k: v for k, v in r.items()
                                   if k != "tekster"} for r in resultater]},
                  f, ensure_ascii=False, indent=2)
    print(f"\n  Lagret: {os.path.relpath(args.ut, ROT)}")
    return 0 if gyldig else 1


if __name__ == "__main__":
    sys.exit(main())
