"""
Evidence Selection som en MÅLT kapabilitet — de sju KPI-ene i §13.1.

    .pyruntime\\python.exe skript\\kjor_bevis_kpi.py            # alle
    .pyruntime\\python.exe skript\\kjor_bevis_kpi.py --uten-server

§13.1 sier det rett ut: «Evidence Selection skal behandles som en målbar
produktkapabilitet. Alle varianter sammenlignes mot en eksplisitt
baseline, slik at kvalitet kan veies mot kontekstkostnad, latency,
GPU-tid og utviklingskostnad. Baseline: first-N-context.»

Det er også halve akseptansen for Phase 1 (§24): «Målt gevinst fra lokal
parallellitet OG evidence selection». Den første halvdelen er målt
(1,70×, R205). Dette er den andre.

BASELINEN ER GITT AV SPESIFIKASJONEN, IKKE VALGT AV OSS
`first-N-context` betyr: ta de N første sidene. N settes til det samme
sidebudsjettet bevisvalg får, så de to konkurrerer om NØYAKTIG samme
kontekstkostnad. Da måler sammenligningen det den skal — hvilke sider
som velges — og ikke hvem som fikk sende mest tekst.

TO HALVDELER, OG BARE DEN ENE TRENGER SERVEREN
  Uten server: candidate_precision, candidate_recall, evidence_recall,
               context_tokens. Rene funksjoner av sidevalget, og de
               regnes på `delt/bevisvalg.py` direkte — raskt og likt
               hver gang.
  Med server:  answer_accuracy, LLM_latency, GPU_seconds_per_answer.
               De krever at modellen faktisk svarer.

FASITEN OG DENS GRENSER
`fasit_sider` er utledet av `skript/utled_fasit_sider.py`. 21 spørsmål
har `null` — svaret står ikke ordrett noe sted (utregnede summer,
spørsmål om dokumentets struktur) — og de holdes UTENFOR
precision/recall. Å telle dem som «ingen side» ville straffet
seleksjonen for å velge sider den skulle valgt.
"""
import argparse
import json
import os
import sys
import time

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "skript"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                               # noqa: BLE001
    pass

BASE = os.environ.get("DOKUMENT_API_BASE", "http://127.0.0.1:8600")
KORPUS = os.path.join(ROT, "tester", "korpus",
                      "sporsmaal_syntetisk_bunke.json")
BUNKE = os.path.join(ROT, "data", "korpus", "syntetisk_bunke_tekstlag.pdf")

# Tegn per token. Grovt, og med vilje: §13.1 vil ha kontekstkostnad
# SAMMENLIGNET mellom to varianter, og et konstant forhold gir riktig
# forholdstall selv om det absolutte tallet er omtrentlig.
TEGN_PER_TOKEN = 4


def sidetekster() -> dict:
    import fitz
    d = fitz.open(BUNKE)
    ut = {i + 1: (d[i].get_text() or "") for i in range(d.page_count)}
    d.close()
    return ut


def _kpi_for_utvalg(valgte, fasit) -> tuple:
    """(presisjon, dekning, alt_med) for ETT spørsmål."""
    v, f = set(valgte), set(fasit)
    traff = len(v & f)
    presisjon = traff / len(v) if v else 0.0
    dekning = traff / len(f) if f else 1.0
    return presisjon, dekning, f <= v


def mal_sidevalg(korpus, sider, maks_sider) -> dict:
    """Den halvdelen som ikke trenger serveren."""
    from delt import bevisvalg

    alle_sidetall = sorted(sider)
    forste_n = alle_sidetall[:maks_sider]          # baseline: first-N
    tegn_per_side = {n: len(t) for n, t in sider.items()}

    ut = {"bevisvalg": {"p": [], "r": [], "alt": [], "tegn": []},
          "first_n": {"p": [], "r": [], "alt": [], "tegn": []},
          "vurdert": 0, "utenfor": 0}

    for sp in korpus["sporsmaal"]:
        fasit = sp.get("fasit_sider")
        if fasit is None:
            ut["utenfor"] += 1
            continue
        ut["vurdert"] += 1
        b = bevisvalg.velg_sider(sider, sp["sporsmal"], maks_sider=maks_sider)
        # `alle: true` betyr at ingen side skilte seg ut og ALT ble sendt
        valgte = b["valgte"] or alle_sidetall
        for navn, utvalg in (("bevisvalg", valgte), ("first_n", forste_n)):
            p, r, alt = _kpi_for_utvalg(utvalg, fasit)
            ut[navn]["p"].append(p)
            ut[navn]["r"].append(r)
            ut[navn]["alt"].append(alt)
            ut[navn]["tegn"].append(sum(tegn_per_side[n] for n in utvalg))
    return ut


def _nokkel() -> str:
    for linje in open(os.path.join(ROT, ".env"), encoding="utf-8"):
        if linje.startswith("API_NOKKEL="):
            return linje.split("=", 1)[1].strip()
    return ""


def mal_svar(korpus, antall=None) -> dict:
    """answer_accuracy + LLM_latency + GPU_seconds mot kjørende server."""
    import requests
    import kjor_sporsmaalskorpus as kk

    nokkel = _nokkel()
    sporsmaal = [s for s in korpus["sporsmaal"] if s.get("svares_av") != "kode"]
    if antall:
        sporsmaal = sporsmaal[:antall]
    riktige, tider = 0, []
    with open(BUNKE, "rb") as f:
        data = f.read()
    for i, sp in enumerate(sporsmaal, 1):
        t0 = time.perf_counter()
        r = requests.post(BASE + "/dokument",
                          files={"fil": ("b.pdf", data, "application/pdf")},
                          data={"sporsmal": sp["sporsmal"], "struktur": "ja"},
                          headers={"X-API-Key": nokkel}, timeout=600)
        tider.append(time.perf_counter() - t0)
        d = r.json()
        ok, _ = kk.vurder_svar(sp, kk._svarteksten(d), d)
        riktige += 1 if ok else 0
        if i % 20 == 0:
            print(f"      {i}/{len(sporsmaal)} …", flush=True)
    tider.sort()
    return {"antall": len(sporsmaal), "riktige": riktige,
            "andel": riktige / max(1, len(sporsmaal)),
            "latency_median": tider[len(tider) // 2] if tider else None,
            "latency_p95": tider[int(len(tider) * 0.95)] if tider else None,
            "gpu_sekunder_per_svar": _gpu_per_svar()}


def _gpu_per_svar():
    """GPU_seconds_per_answer fra /metrics — tellerne finnes alt."""
    try:
        import requests
        t = requests.get(BASE + "/metrics", timeout=20).text
        kall = sek = None
        for linje in t.splitlines():
            if linje.startswith("nav_modellkall_total "):
                kall = float(linje.split()[-1])
            elif linje.startswith("nav_modell_sekunder_total "):
                sek = float(linje.split()[-1])
        if kall and sek is not None:
            return round(sek / kall, 3)
    except Exception:                                           # noqa: BLE001
        pass
    return None


def _snitt(xs):
    return sum(xs) / len(xs) if xs else 0.0


def main() -> int:
    p = argparse.ArgumentParser(description="Evidence Selection KPI (§13.1)")
    p.add_argument("--uten-server", action="store_true",
                   help="bare de fire som ikke trenger modellen")
    p.add_argument("--antall", type=int, default=None,
                   help="begrens antall spørsmål mot serveren")
    p.add_argument("--maks-sider", type=int, default=int(
        os.environ.get("BEVISVALG_MAKS_SIDER", "5")))
    p.add_argument("--ut", default=os.path.join(
        ROT, "data", "maalinger", "bevis_kpi.json"))
    args = p.parse_args()

    korpus = json.load(open(KORPUS, encoding="utf-8"))
    if "fasit_sider" not in (korpus["sporsmaal"][0] or {}):
        raise SystemExit("Korpuset mangler «fasit_sider» — kjør "
                         "skript/utled_fasit_sider.py --skriv først.")
    sider = sidetekster()

    print("=" * 72)
    print("  EVIDENCE SELECTION — KPI-ene i §13.1")
    print(f"  Baseline: first-{args.maks_sider}-context "
          f"(samme sidebudsjett som bevisvalg får)")
    print("=" * 72)

    s = mal_sidevalg(korpus, sider, args.maks_sider)
    print(f"\n  Spørsmål med utledbar fasit : {s['vurdert']}")
    print(f"  Holdt utenfor (fasit=null)  : {s['utenfor']}\n")
    print(f"  {'KPI':<26}{'first-N':>12}{'bevisvalg':>12}{'endring':>12}")
    print("  " + "-" * 60)
    rader = []
    for navn, nokkel, kilde in (
            ("candidate_precision", "p", "snitt"),
            ("candidate_recall", "r", "snitt"),
            ("evidence_recall", "alt", "andel"),
            ("context_tokens", "tegn", "tokens")):
        a = s["first_n"][nokkel]
        b = s["bevisvalg"][nokkel]
        if kilde == "andel":
            va, vb = _snitt([1.0 if x else 0.0 for x in a]), \
                     _snitt([1.0 if x else 0.0 for x in b])
            fa, fb = f"{va:.1%}", f"{vb:.1%}"
        elif kilde == "tokens":
            va, vb = _snitt(a) / TEGN_PER_TOKEN, _snitt(b) / TEGN_PER_TOKEN
            fa, fb = f"{va:.0f}", f"{vb:.0f}"
        else:
            va, vb = _snitt(a), _snitt(b)
            fa, fb = f"{va:.1%}", f"{vb:.1%}"
        endring = ("—" if not va else
                   f"{(vb - va) / va:+.1%}" if kilde != "tokens"
                   else f"{(vb - va) / va:+.1%}")
        print(f"  {navn:<26}{fa:>12}{fb:>12}{endring:>12}")
        rader.append({"kpi": navn, "first_n": va, "bevisvalg": vb})

    svar = None
    if not args.uten_server:
        print(f"\n  Måler answer_accuracy mot serveren "
              f"({'alle' if not args.antall else args.antall} spørsmål) …",
              flush=True)
        try:
            svar = mal_svar(korpus, args.antall)
            print(f"\n  {'answer_accuracy':<26}"
                  f"{svar['riktige']}/{svar['antall']} "
                  f"({svar['andel']:.1%})")
            print(f"  {'LLM_latency (median)':<26}"
                  f"{svar['latency_median']:.2f} s")
            print(f"  {'LLM_latency (p95)':<26}{svar['latency_p95']:.2f} s")
            print(f"  {'GPU_seconds_per_answer':<26}"
                  f"{svar['gpu_sekunder_per_svar']}")
        except Exception as exc:                                # noqa: BLE001
            print(f"    kunne ikke måle mot serveren: {exc}")

    print("\n" + "=" * 72)
    os.makedirs(os.path.dirname(args.ut), exist_ok=True)
    with open(args.ut, "w", encoding="utf-8") as f:
        json.dump({"baseline": f"first-{args.maks_sider}-context",
                   "maks_sider": args.maks_sider,
                   "vurdert": s["vurdert"], "utenfor": s["utenfor"],
                   "sidevalg": rader, "svar": svar},
                  f, ensure_ascii=False, indent=2)
    print(f"  Lagret: {os.path.relpath(args.ut, ROT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
