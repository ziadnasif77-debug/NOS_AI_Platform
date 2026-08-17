"""
R6-porten: samme dokument N ganger — er slutt-JSON identisk? (§26/§30)

    .pyruntime\\python.exe skript\\kjor_determinismeport.py
    .pyruntime\\python.exe skript\\kjor_determinismeport.py --antall 10

Spesifikasjonen krever det to steder, med samme ordlyd begge ganger:
«Samme dokument kjørt 10 ganger under identisk engine/model/configuration
skal gi byte-for-byte identisk resultat-JSON (R6)». Det var aldri prøvd:
det nærmeste var to kjøringer av 500-sidersmålingen og tre spørsmål i
spørsmålskorpuset.

CACHEN MÅ VÆRE AV — ELLERS MÅLER PORTEN INGENTING
Sendes samme fil ti ganger med cachen på, svarer `analyser_med_cache`
fra minnet fra og med kjøring 2. Da beviser porten at cachen er stabil,
ikke at lesingen er deterministisk — og det er det siste §26 spør om.
Derfor kreves serveren startet med `ANALYSE_CACHE_MAKS=0`, og porten
SJEKKER det selv: kom ett eneste svar fra cachen, er runden ugyldig.

Alternativet — å gjøre hver opplasting byte-ulik for å bomme på cachen —
ble valgt bort med vilje. Da måler man ikke lenger «samme dokument», og
felter som gjenspeiler filstørrelse ville sett ut som ustabilitet.

FLYKTIGE FELTER
Noen felter KAN ikke være like: målt kjøretid er en måling. De står i
`FLYKTIGE` med en begrunnelse hver, og sammenligningen gjøres uten dem.
Alt annet som varierer, meldes som FUNN — lista er en erklæring, ikke et
sluk. En vakttest (`tester/test_determinismeport.py`) sørger for at den
ikke vokser i stillhet, for det er nøyaktig slik en port slutter å bety
noe: ett felt om gangen, hver med sin lille grunn.
"""
import argparse
import copy
import hashlib
import json
import os
import sys
import time

import requests

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                               # noqa: BLE001
    pass

BASE = os.environ.get("DOKUMENT_API_BASE", "http://127.0.0.1:8600")

# Felter som IKKE kan være like mellom to kjøringer, med grunnen sin.
# Hver nøkkel er et feltnavn slik det står i svaret, på hvilket som helst
# nivå. Lista skal være kort, og hver linje skal kunne forsvares alene.
FLYKTIGE = {
    "tid_sekunder": "målt kjøretid — en måling, ikke et resultat",
}

# Dokumentene porten kjøres på. Determinisme på ÉN vei er ikke
# determinisme: tekstlaget hopper over OCR helt, det skannede går
# gjennom hele OCR-veien, og bunken legger sidedeling og bevisvalg oppå.
DOKUMENTER = [
    ("tekstlag", "syntetisk_bunke_tekstlag.pdf", {"struktur": "ja"}),
    ("skannet", "syntetisk_bunke_skann.pdf", {"struktur": "ja"}),
    ("bunke+spørsmål", "syntetisk_bunke_tekstlag.pdf",
     {"struktur": "ja", "sporsmal": "Hva er saksnummeret?"}),
    # Den strengeste av dem. De tre over har korte, uttrekkbare svar —
    # et saksnummer står der eller ikke. Her GENERERER modellen fri
    # tekst, og det er der determinisme faktisk kan ryke: sampling,
    # rekkefølge på flyttall, KV-cache-tilstand. Er dette identisk ti
    # ganger, er R6 prøvd på den vanskeligste veien vi har.
    ("fritekst fra modell", "syntetisk_bunke_tekstlag.pdf",
     {"struktur": "nei", "sporsmal":
      "Oppsummer hva dette dokumentet handler om med egne ord"}),
]


def _nokkel() -> str:
    for linje in open(os.path.join(ROT, ".env"), encoding="utf-8"):
        if linje.startswith("API_NOKKEL="):
            return linje.split("=", 1)[1].strip()
    return ""


def uten_flyktige(node):
    """Svaret uten feltene som ikke KAN være like. Rekursivt, fordi de
    kan ligge på hvilket som helst nivå (`svar.tid_sekunder`)."""
    if isinstance(node, dict):
        return {k: uten_flyktige(v) for k, v in node.items()
                if k not in FLYKTIGE}
    if isinstance(node, list):
        return [uten_flyktige(v) for v in node]
    return node


def kanonisk(node) -> str:
    """Samme innhold gir samme streng. Nøkkelrekkefølge i en ordbok er
    et artefakt av hvordan svaret ble bygget, ikke en del av det."""
    return json.dumps(node, ensure_ascii=False, sort_keys=True, indent=None)


def _stier_som_avviker(a, b, sti=""):
    """Hvilke felter skiller seg — som lesbare stier, ikke som en diff
    på 300 000 tegn."""
    ut = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                ut.append((f"{sti}.{k}", "MANGLER i kjøring 1", "finnes"))
            elif k not in b:
                ut.append((f"{sti}.{k}", "finnes", "MANGLER"))
            else:
                ut += _stier_som_avviker(a[k], b[k], f"{sti}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            ut.append((f"{sti}[]", f"{len(a)} elementer", f"{len(b)} elementer"))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                ut += _stier_som_avviker(x, y, f"{sti}[{i}]")
    elif a != b:
        ut.append((sti or "(rot)", repr(a)[:70], repr(b)[:70]))
    return ut


def kjor_ett(navn: str, fil: str, felt: dict, antall: int, nokkel: str) -> dict:
    sti = os.path.join(ROT, "data", "korpus", fil)
    if not os.path.isfile(sti):
        return {"navn": navn, "feil": f"fant ikke {sti}"}
    with open(sti, "rb") as f:
        data = f.read()

    print(f"\n  [{navn}]  {fil}  ({len(data) / 1024:.0f} KB)  ×{antall}",
          flush=True)
    svar, fra_cache, raa = [], [], []
    for i in range(antall):
        t0 = time.perf_counter()
        r = requests.post(BASE + "/dokument",
                          files={"fil": (fil, data, "application/pdf")},
                          data=felt, headers={"X-API-Key": nokkel},
                          timeout=900)
        r.raise_for_status()
        d = r.json()
        svar.append(d)
        raa.append(r.content)
        fra_cache.append(bool(d.get("fra_cache")))
        print(f"      kjøring {i + 1:2d}/{antall}  "
              f"{time.perf_counter() - t0:6.1f} s  "
              f"fra_cache={d.get('fra_cache')}", flush=True)

    # Kom noe fra cachen, målte vi cachen — ikke lesingen.
    if any(fra_cache[1:]):
        return {"navn": navn, "ugyldig": True, "fra_cache": fra_cache,
                "grunn": ("svar kom fra cachen — start serveren med "
                          "ANALYSE_CACHE_MAKS=0, ellers beviser porten "
                          "bare at cachen er stabil")}

    fasit = uten_flyktige(svar[0])
    fasit_tekst = kanonisk(fasit)
    avvikende, alle_stier = [], []
    for i in range(1, antall):
        denne = kanonisk(uten_flyktige(svar[i]))
        if denne != fasit_tekst:
            avvikende.append(i + 1)
            alle_stier += _stier_som_avviker(fasit, uten_flyktige(svar[i]))

    raa_like = all(b == raa[0] for b in raa[1:])
    return {"navn": navn, "antall": antall, "avvikende": avvikende,
            "stier": alle_stier, "raa_like": raa_like,
            "tegn": len(fasit_tekst)}


def main() -> int:
    p = argparse.ArgumentParser(description="R6-determinismeport (§26/§30)")
    p.add_argument("--antall", type=int, default=10,
                   help="antall kjøringer per dokument (spesifikasjonen: 10)")
    p.add_argument("--ut", default=os.path.join(
        ROT, "data", "maalinger", "determinismeport.json"))
    args = p.parse_args()

    nokkel = _nokkel()
    print("=" * 70)
    print(f"  R6-DETERMINISMEPORT — {args.antall} kjøringer per dokument")
    print(f"  Flyktige felter (utelatt fra sammenligningen):")
    for f, grunn in FLYKTIGE.items():
        print(f"      {f}: {grunn}")
    print("=" * 70)

    resultater = [kjor_ett(navn, fil, felt, args.antall, nokkel)
                  for navn, fil, felt in DOKUMENTER]

    print()
    print("=" * 70)
    bestatt = True
    for r in resultater:
        if r.get("feil"):
            print(f"  {r['navn']:<16} FEIL: {r['feil']}")
            bestatt = False
            continue
        if r.get("ugyldig"):
            print(f"  {r['navn']:<16} UGYLDIG: {r['grunn']}")
            bestatt = False
            continue
        if r["avvikende"]:
            print(f"  {r['navn']:<16} AVVIK i kjøring {r['avvikende']}")
            bestatt = False
            sett = set()
            for sti, a, b in r["stier"]:
                if sti in sett:
                    continue
                sett.add(sti)
                print(f"        {sti}")
                print(f"          kjøring 1 : {a}")
                print(f"          senere    : {b}")
        else:
            raa = "og RÅ svarbytes også" if r["raa_like"] else \
                  "(rå bytes varierer — flyktige felter)"
            print(f"  {r['navn']:<16} IDENTISK i alle {r['antall']} "
                  f"kjøringer {raa}")
    print("=" * 70)
    print(f"\n  PORTEN: {'BESTÅTT' if bestatt else 'STRØK'}")

    os.makedirs(os.path.dirname(args.ut), exist_ok=True)
    with open(args.ut, "w", encoding="utf-8") as f:
        json.dump({"antall": args.antall, "flyktige": FLYKTIGE,
                   "bestatt": bestatt, "resultater": resultater},
                  f, ensure_ascii=False, indent=2)
    print(f"  Lagret: {os.path.relpath(args.ut, ROT)}")
    return 0 if bestatt else 1


if __name__ == "__main__":
    sys.exit(main())
