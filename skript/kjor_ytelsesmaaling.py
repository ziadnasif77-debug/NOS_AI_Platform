"""
Phase 0-riggen: måler hva DENNE maskinen faktisk klarer.

    .pyruntime\\python.exe skript\\kjor_ytelsesmaaling.py
    .pyruntime\\python.exe skript\\kjor_ytelsesmaaling.py --runder 20 --samtidige 8

Konseptutredningen krever før noen ny infrastruktur vurderes: en målt
bottleneck, en baseline, og en benchmark som kan bekrefte eller avkrefte
hypotesen (§20.0). Dette skriptet lager de tre.

DEN VIKTIGSTE EGENSKAPEN ER AT DEN KAN KJØRES ET ANNET STED.
Tallene herfra gjelder maskinen de ble målt på. Skal de brukes til å
dimensjonere en NAV-server, må riggen kjøres PÅ den serveren — og det er
hele grunnen til at dette er et skript og ikke et notat. Rapporten
stempler derfor alltid maskinen den kjørte på.

FIRE LEDD, MÅLT HVER FOR SEG
Utredningen ber om tall per ledd, ikke bare en totaltid. Sammenligningen
mellom målingene isolerer dem:

    A  tekstlag, kun felter      →  parsing + deterministisk motor
    B  tekstlag, struktur=ja     →  B−A = fullt strukturert uttrekk
    C  tekstlag + spørsmål       →  C−A = Borealis (bekreftes mot /metrics)
    D  skannet, kun felter       →  D−A = OCR (bekreftes mot /metrics)

CACHEN MÅ BESEIRES, ELLERS MÅLER VI INGENTING
Serveren cacher analysen på filens innhold. Kjører man samme fil ti
ganger, måler man cachen i ni av dem — og får et tall som ser fantastisk
ut og betyr null. Hver runde sender derfor en unik variant av filen.
Cachetreff måles SEPARAT, for det er en ekte og viktig egenskap:
oppfølgingsspørsmål på samme dokument er nesten gratis.
"""
import argparse
import io
import json
import os
import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                               # noqa: BLE001
    pass

BASE = os.environ.get("KORPUS_API", "http://127.0.0.1:8600")
TEKSTLAG = os.path.join(ROT, "data", "korpus", "syntetisk_bunke_tekstlag.pdf")
SKANN = os.path.join(ROT, "data", "korpus", "syntetisk_bunke_skann.pdf")
UT_MAPPE = os.path.join(ROT, "data", "ytelsesmaalinger")


def _nokkel() -> str:
    nokkel = os.environ.get("API_NOKKEL", "")
    if nokkel:
        return nokkel
    try:
        with open(os.path.join(ROT, ".env"), encoding="utf-8") as f:
            for linje in f:
                if linje.startswith("API_NOKKEL="):
                    return linje.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def unik(data: bytes, nr: int) -> bytes:
    """En variant av PDF-en som er FUNKSJONELT lik, men har en annen
    hash — ellers svarer cachen og målingen blir meningsløs.

    Kommentaren legges etter %%EOF. PDF-lesere (og fitz) leser fra
    krysstabellen og ignorerer haleteksten, så innholdet er identisk;
    bare filens fingeravtrykk endres."""
    return data + f"\n% maaling-{nr}-{time.time_ns()}\n".encode()


def _metrics() -> dict:
    """Tellerne akkurat nå — differansen mellom to avlesninger gir
    HVOR tiden gikk, ikke bare hvor lang den var."""
    try:
        with urllib.request.urlopen(BASE + "/metrics", timeout=20) as svar:
            tekst = svar.read().decode("utf-8")
    except Exception:                                           # noqa: BLE001
        return {}
    ut = {}
    for linje in tekst.splitlines():
        if linje.startswith("#") or " " not in linje:
            continue
        navn, _, verdi = linje.rpartition(" ")
        try:
            ut[navn] = float(verdi)
        except ValueError:
            continue
    return ut


def _kall(sti_fil: bytes, filnavn: str, felter: dict, nokkel: str,
          frist: int = 900):
    import requests
    t0 = time.perf_counter()
    svar = requests.post(
        BASE + "/dokument",
        files={"fil": (filnavn, io.BytesIO(sti_fil), "application/pdf")},
        data=felter, headers={"X-API-Key": nokkel}, timeout=frist)
    brukt = time.perf_counter() - t0
    try:
        kropp = svar.json()
    except ValueError:
        kropp = {}
    return brukt, svar.status_code, kropp


def _persentil(verdier, andel: float) -> float:
    """P95 uten numpy. Nærmeste rangering — på små utvalg er det
    ærligere enn interpolasjon, som later som det finnes en presisjon
    utvalget ikke bærer."""
    if not verdier:
        return 0.0
    sortert = sorted(verdier)
    i = min(len(sortert) - 1, max(0, int(round(andel * len(sortert) + 0.5)) - 1))
    return sortert[i]


def _sammendrag(tider) -> dict:
    return {
        "antall": len(tider),
        "min": round(min(tider), 3) if tider else None,
        "median": round(statistics.median(tider), 3) if tider else None,
        "p95": round(_persentil(tider, 0.95), 3),
        "p99": round(_persentil(tider, 0.99), 3),
        "maks": round(max(tider), 3) if tider else None,
        "snitt": round(statistics.fmean(tider), 3) if tider else None,
    }


def mal_scenario(navn: str, fil: str, felter: dict, runder: int,
                 nokkel: str) -> dict:
    """Ett scenario, `runder` ganger, med unik fil hver gang."""
    if not os.path.isfile(fil):
        return {"navn": navn, "feil": f"mangler {fil}"}
    raa = open(fil, "rb").read()
    print(f"\n  {navn}: {runder} runder ...", flush=True)
    for_ = _metrics()
    tider, koder = [], {}
    for nr in range(runder):
        brukt, kode, kropp = _kall(unik(raa, nr), os.path.basename(fil),
                                   felter, nokkel)
        koder[str(kode)] = koder.get(str(kode), 0) + 1
        if kode == 200 and not kropp.get("fra_cache"):
            tider.append(brukt)
        print(f"    {nr + 1:>3}/{runder}  {brukt:6.2f} s  ({kode})", flush=True)
    etter = _metrics()

    def delta(n):
        return round(etter.get(n, 0.0) - for_.get(n, 0.0), 3)

    return {
        "navn": navn, "felter": felter, "koder": koder,
        "tid": _sammendrag(tider),
        "av_dette": {
            "ocr_sekunder": delta("nav_ocr_sekunder_total"),
            "ocr_sider": delta("nav_ocr_sider_total"),
            "modell_sekunder": delta("nav_modell_sekunder_total"),
            "modellkall": delta("nav_modellkall_total"),
        },
    }


def mal_cachetreff(fil: str, nokkel: str, runder: int = 5) -> dict:
    """SAMME fil om igjen. Ikke juks — en ekte og viktig egenskap:
    oppfølgingsspørsmål på et dokument som alt er lest, koster nesten
    ingenting. Blandes den med kaldmålingene, lyver begge."""
    raa = unik(open(fil, "rb").read(), 999_999)
    print(f"\n  Cachetreff (samme fil {runder}x) ...", flush=True)
    tider = []
    for nr in range(runder):
        brukt, kode, kropp = _kall(raa, "cache.pdf", {"tekst": "nei"}, nokkel)
        if nr > 0 and kode == 200:          # første runde er den kalde
            tider.append(brukt)
        print(f"    {nr + 1}/{runder}  {brukt:6.2f} s  "
              f"(fra_cache={kropp.get('fra_cache')})", flush=True)
    return {"navn": "cachetreff", "tid": _sammendrag(tider)}


def mal_samtidighet(fil: str, nokkel: str, samtidige: int) -> dict:
    """Hva skjer når flere kommer samtidig? Utredningen krever at 100
    samtidige brukere ikke gir kollaps, og at interaktive forespørsler
    beholder kapasitet under batch. Her måles den ENE tingen som
    avgjør det: slipper porten inn flere enn maskinen bærer?"""
    raa = open(fil, "rb").read()
    print(f"\n  Samtidighet: {samtidige} parallelle ...", flush=True)
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=samtidige) as pool:
        resultater = list(pool.map(
            lambda nr: _kall(unik(raa, 5000 + nr), "samtidig.pdf",
                             {"tekst": "nei"}, nokkel),
            range(samtidige)))
    veggtid = time.perf_counter() - t0
    tider = [b for b, k, _ in resultater if k == 200]
    koder = {}
    for _, k, _ in resultater:
        koder[str(k)] = koder.get(str(k), 0) + 1
    return {
        "navn": f"samtidighet_{samtidige}",
        "samtidige": samtidige,
        "veggtid_sekunder": round(veggtid, 2),
        "gjennomstromning_per_sekund": round(len(tider) / veggtid, 2)
        if veggtid else 0,
        "koder": koder, "tid": _sammendrag(tider),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Phase 0-måling")
    p.add_argument("--runder", type=int, default=10)
    p.add_argument("--samtidige", type=int, default=4)
    p.add_argument("--hopp-over-skann", action="store_true",
                   help="OCR-scenarioet er det tregeste — hopp over ved "
                        "en rask kontrollkjøring")
    args = p.parse_args()

    nokkel = _nokkel()
    try:
        with urllib.request.urlopen(BASE + "/hjelp", timeout=20) as s:
            hjelp = json.loads(s.read())
    except Exception as exc:                                    # noqa: BLE001
        print(f"[FEIL] Serveren svarer ikke på {BASE}: {exc}")
        print("       Start den først (oppstart\\start_api_med_vakthund.bat).")
        return 1
    if hjelp.get("borealis") != "klar":
        print(f"[ADV]  Borealis er «{hjelp.get('borealis')}», ikke «klar». "
              "Modelltallene blir ikke representative.")

    from delt import maskinprofil
    print("=" * 66)
    print("  PHASE 0 — YTELSESMÅLING")
    print("=" * 66)
    print(maskinprofil.rapport())

    scenarier = [
        mal_scenario("A_tekstlag_felter", TEKSTLAG,
                     {"tekst": "nei"}, args.runder, nokkel),
        mal_scenario("B_tekstlag_struktur", TEKSTLAG,
                     {"tekst": "nei", "struktur": "ja"}, args.runder, nokkel),
        mal_scenario("C_tekstlag_sporsmal", TEKSTLAG,
                     {"tekst": "nei", "sporsmal": "Hva er saksnummeret?"},
                     max(3, args.runder // 2), nokkel),
    ]
    if not args.hopp_over_skann:
        scenarier.append(mal_scenario(
            "D_skannet_felter", SKANN, {"tekst": "nei"},
            max(3, args.runder // 3), nokkel))
    scenarier.append(mal_cachetreff(TEKSTLAG, nokkel))
    scenarier.append(mal_samtidighet(TEKSTLAG, nokkel, args.samtidige))

    profil = maskinprofil.profil()
    rapport = {
        "tidspunkt": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "maskin": profil["maaling"],
        "tak": profil["valgt"],
        "borealis": {"status": hjelp.get("borealis"),
                     "modell": hjelp.get("borealis_modell"),
                     "motor": hjelp.get("borealis_motor")},
        "ocr": hjelp.get("ocr"),
        "scenarier": scenarier,
    }
    try:
        os.makedirs(UT_MAPPE, exist_ok=True)
        sti = os.path.join(
            UT_MAPPE, datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
        with open(sti, "w", encoding="utf-8") as f:
            json.dump(rapport, f, ensure_ascii=False, indent=2)
        print(f"\n  Lagret: {os.path.relpath(sti, ROT)}")
    except OSError as exc:
        print(f"\n  (kunne ikke lagre: {exc})")

    skriv_sammendrag(rapport)
    return 0


def skriv_sammendrag(rapport: dict) -> None:
    print("\n" + "=" * 66)
    print("  SAMMENDRAG")
    print("=" * 66)
    print(f"  {'Scenario':<24} {'median':>8} {'P95':>8} {'P99':>8}  av dette")
    etter_navn = {s["navn"]: s for s in rapport["scenarier"]}
    for s in rapport["scenarier"]:
        if s.get("feil"):
            print(f"  {s['navn']:<24} {s['feil']}")
            continue
        t = s["tid"]
        av = s.get("av_dette") or {}
        deler = []
        if av.get("ocr_sekunder"):
            deler.append(f"OCR {av['ocr_sekunder']:.1f} s "
                         f"({av['ocr_sider']:.0f} sider)")
        if av.get("modell_sekunder"):
            deler.append(f"modell {av['modell_sekunder']:.1f} s "
                         f"({av['modellkall']:.0f} kall)")
        print(f"  {s['navn']:<24} {t['median'] or 0:>8.2f} {t['p95']:>8.2f} "
              f"{t['p99']:>8.2f}  {', '.join(deler)}")

    # De avledede tallene utredningen faktisk spør etter
    print()
    a = etter_navn.get("A_tekstlag_felter", {}).get("tid", {})
    d = etter_navn.get("D_skannet_felter")
    if d and not d.get("feil"):
        av = d["av_dette"]
        if av.get("ocr_sekunder") and av.get("ocr_sider"):
            fart = av["ocr_sider"] / av["ocr_sekunder"]
            print(f"  OCR-FART:            {fart:.2f} sider/sekund "
                  f"({av['ocr_sekunder'] / av['ocr_sider']:.2f} s/side)")
            behov = 5.2 / fart * 1.3
            print(f"  ARBEIDERE VED 5,2 sider/s (utredningens topplast, "
                  f"sikkerhetsfaktor 1,3):  {behov:.0f}")
    if a.get("median"):
        print(f"  DETERMINISTISK VEI:  median {a['median']:.2f} s, "
              f"P95 {a['p95']:.2f} s  (parsing + uttrekk, uten OCR og modell)")
    c = etter_navn.get("C_tekstlag_sporsmal")
    if c and not c.get("feil") and c["av_dette"].get("modellkall"):
        av = c["av_dette"]
        print(f"  MODELLKALL:          "
              f"{av['modell_sekunder'] / max(1, av['modellkall']):.2f} s "
              "per kall")
    s = etter_navn.get(f"samtidighet_{rapport['scenarier'][-1].get('samtidige')}")
    if s:
        print(f"  SAMTIDIGHET:         {s['samtidige']} parallelle → "
              f"{s['gjennomstromning_per_sekund']:.2f} svar/s, "
              f"koder {s['koder']}")
    print("\n  Tallene gjelder MASKINEN OVER. Skal de dimensjonere en "
          "NAV-server,\n  må riggen kjøres der.")


if __name__ == "__main__":
    sys.exit(main())
