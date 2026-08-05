"""
klientrapport.py — hvem bruker hva?

Dette er hele poenget med navngitte API-nøkler (R91). Revisjonen slo
fast at ingen felter kunne fjernes så lenge hver forespørsel var anonym:
spørsmålet «bruker noen fortsatt dette?» hadde ikke noe svar, så et
utgått felt måtte stå for alltid — for sikkerhets skyld.

Rapporten leser tilgangsloggen og svarer på det loggen FAKTISK vet:

    python skript/klientrapport.py                  # siste 30 dager
    python skript/klientrapport.py --dager 7
    python skript/klientrapport.py --sti /analyser  # hvem bruker dette?

HVA LOGGEN KAN OG IKKE KAN SVARE PÅ
    Loggen ser FORESPØRSELEN. Den kan derfor svare sikkert på:
      · Kaller noen fortsatt /analyser, /spor, /uttrekk? (kan de pensjoneres?)
      · Hvem bruker en utgått BRYTER?
      · Hvilken klient står for lasten?

    Den kan IKKE svare på hvilke FELTER en klient leser i svaret. At
    ingen lenger bruker `eier` i stedet for `part` er usynlig herfra —
    begge står i samme svar, og serveren ser ikke hva klienten plukker
    ut. Utgåtte SVARfelter må derfor varsles i `varsler[]` og fjernes
    etter et annonsert løp, ikke fordi denne rapporten sier de er ubrukte.

    Den forskjellen står her fordi en rapport som ser fullstendig ut, men
    ikke er det, er farligere enn ingen rapport: da fjernes et felt i god
    tro, og en klient brekker.
"""
import json
import os
import sys
import time
from collections import Counter, defaultdict

# Konsollet på Windows kan stå i en kodeside som ikke har æøå (målt:
# cp1256). Da krasjer en NORSK rapport på sine egne bokstaver. Samme grep
# som resten av skriptene i mappa.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TILGANGSLOGG_STI = os.environ.get("TILGANGSLOGG", "data/logger/tilgang.log")


def les_rader(sti: str, fra_tid: float = 0.0) -> list:
    """Radene i loggen som er nyere enn `fra_tid`. Ugyldige linjer hoppes
    over uten å stoppe rapporten — en halvskrevet siste linje er normalt
    når serveren kjører mens dette leses."""
    rader = []
    if not os.path.exists(sti):
        return rader
    with open(sti, encoding="utf-8", errors="replace") as f:
        for linje in f:
            linje = linje.strip()
            if not linje:
                continue
            try:
                rad = json.loads(linje)
            except ValueError:
                continue
            if fra_tid and _tid(rad) < fra_tid:
                continue
            rader.append(rad)
    return rader


def _tid(rad: dict) -> float:
    try:
        return time.mktime(time.strptime(rad.get("t", ""), "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return 0.0


def oppsummer(rader: list) -> dict:
    """Kall per klient, og hvilke stier hver klient bruker."""
    per_klient = Counter()
    stier = defaultdict(Counter)
    feil = Counter()
    anonyme = 0
    for rad in rader:
        klient = rad.get("klient_id")
        if not klient:
            anonyme += 1
            continue
        per_klient[klient] += 1
        stier[klient][rad.get("sti", "?")] += 1
        kode = rad.get("kode")
        if isinstance(kode, int) and kode >= 400:
            feil[klient] += 1
    return {"per_klient": per_klient, "stier": stier, "feil": feil,
            "anonyme": anonyme, "totalt": len(rader)}


def hvem_bruker(rader: list, sti: str) -> Counter:
    """Hvilke klienter kaller et gitt endepunkt. Tom teller = ingen har
    kalt det i vinduet — det er svaret man trenger før noe pensjoneres."""
    treff = Counter()
    for rad in rader:
        if rad.get("sti") == sti and rad.get("klient_id"):
            treff[rad["klient_id"]] += 1
    return treff


def _skriv(rapport: dict, dager: int) -> None:
    print(f"Tilgangslogg, siste {dager} dager: {rapport['totalt']} rader\n")
    if not rapport["per_klient"] and not rapport["anonyme"]:
        print("Ingen rader i vinduet.")
        return
    if rapport["per_klient"]:
        bredde = max(len(k) for k in rapport["per_klient"])
        print(f"{'KLIENT'.ljust(bredde)}  {'KALL':>7}  {'FEIL':>5}  STIER")
        for klient, antall in rapport["per_klient"].most_common():
            topp = ", ".join(f"{s} ({n})" for s, n
                             in rapport["stier"][klient].most_common(4))
            print(f"{klient.ljust(bredde)}  {antall:>7}  "
                  f"{rapport['feil'][klient]:>5}  {topp}")
    if rapport["anonyme"]:
        print(f"\n{rapport['anonyme']} rader UTEN klient_id. Enten kjørte "
              f"serveren uten navngitte nøkler, eller radene er eldre enn "
              f"R91.\nDe kan ikke tilskrives noen — og et felt kan ikke "
              f"fjernes på grunnlag av dem.")


def main(argv) -> int:
    dager = 30
    sti_filter = None
    if "--dager" in argv:
        dager = int(argv[argv.index("--dager") + 1])
    if "--sti" in argv:
        sti_filter = argv[argv.index("--sti") + 1]

    logg = os.path.join(ROT, TILGANGSLOGG_STI) \
        if not os.path.isabs(TILGANGSLOGG_STI) else TILGANGSLOGG_STI
    if not os.path.exists(logg):
        print(f"Fant ingen tilgangslogg ({logg}).")
        return 1
    rader = les_rader(logg, time.time() - dager * 86400)

    if sti_filter:
        # En sti som ikke FINNES i loggen gir samme tomme svar som en
        # ubrukt sti — og her betyr det tomme svaret «trygt å pensjonere».
        # Skrivefeil (eller Git Bash, som gjør «/analyser» om til
        # «C:/Program Files/Git/analyser») ville derfor blitt lest som et
        # grønt lys. Derfor sjekkes stien mot dem loggen faktisk kjenner.
        kjente = {rad.get("sti") for rad in rader if rad.get("sti")}
        if sti_filter not in kjente:
            print(f"«{sti_filter}» finnes ikke i loggen — dette er IKKE "
                  f"et svar på om noen bruker den.\n")
            if kjente:
                print("Stier i loggen:")
                for kjent in sorted(kjente):
                    print(f"  {kjent}")
            return 1
        treff = hvem_bruker(rader, sti_filter)
        if not treff:
            print(f"Stien {sti_filter} er kalt i vinduet, men INGEN av "
                  f"kallene har klient_id.\nDe kan ikke tilskrives noen — "
                  f"og et endepunkt kan ikke pensjoneres på det grunnlaget.")
            return 1
        print(f"Klienter som kaller {sti_filter} (siste {dager} dager):\n")
        for klient, antall in treff.most_common():
            print(f"  {klient}: {antall} kall")
        return 0

    _skriv(oppsummer(rader), dager)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
