"""
Verifiserer en offline-bunt mot SHA256SUMS (§26).

    .pyruntime\\python.exe skript\\verifiser_kontrollsummer.py offline_pakke
    .pyruntime\\python.exe skript\\verifiser_kontrollsummer.py --lag offline_pakke

§26: «Offline installasjon skal være reproduserbar og
checksum-verifisert.» Dette er verifiseringen.

DEN SKAL FEILE HØYT
En kontrollsjekk som skriver «advarsel» og fortsetter, er en sjekk ingen
oppdager at feilet. Exitkoden er 1 ved ethvert avvik, og feilen sier
HVILKE filer og HVA slags avvik — for de tre utfallene krever helt ulik
handling:

    mangler   kopieringen ble ikke ferdig      → kopier på nytt
    endret    fila er ødelagt eller byttet     → STOPP, dette er alvorlig
    ekstra    noe er kommet til etterpå        → som regel ufarlig
"""
import argparse
import os
import sys

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                               # noqa: BLE001
    pass

from delt import kontrollsummer                                 # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Kontrollsummer for offline-bunt")
    p.add_argument("mappe", help="mappa som skal lages/verifiseres")
    p.add_argument("--lag", action="store_true",
                   help="LAG SHA256SUMS i stedet for å verifisere")
    p.add_argument("--versjon", default=None)
    args = p.parse_args()

    if not os.path.isdir(args.mappe):
        print(f"  Fant ikke mappa: {args.mappe}")
        return 2

    if args.lag:
        m = kontrollsummer.lag(args.mappe, args.versjon)
        print(f"  SHA256SUMS + release-manifest.json skrevet i {args.mappe}")
        print(f"  Filer: {m['antall_filer']}   "
              f"Størrelse: {m['sum_bytes'] / 1024 ** 2:.0f} MB   "
              f"Versjon: {m['versjon']}")
        return 0

    r = kontrollsummer.verifiser(args.mappe)
    if r.get("grunn"):
        print(f"  KAN IKKE VERIFISERE: {r['grunn']}")
        print("  Lag den først:  verifiser_kontrollsummer.py --lag <mappe>")
        return 1

    print(f"  Sjekket {r['sjekket']} filer i {args.mappe}")
    for navn, liste, hva in (
            ("MANGLER", r["mangler"], "kopieringen ble ikke ferdig — "
                                      "kopier bunten på nytt"),
            ("ENDRET", r["endret"], "fila er ødelagt eller byttet ut — "
                                    "STOPP og finn ut hvorfor"),
            ("EKSTRA", r["ekstra"], "kommet til etter pakking — som regel "
                                    "ufarlig, men ikke en del av bunten")):
        if liste:
            print(f"\n  {navn} ({len(liste)}): {hva}")
            for f in liste[:20]:
                print(f"      {f}")
            if len(liste) > 20:
                print(f"      … og {len(liste) - 20} til")

    if r["ok"]:
        print("\n  BUNTEN ER HEL — alle filer stemmer med SHA256SUMS.")
        return 0
    print("\n  BUNTEN ER IKKE HEL. Ikke installer fra den før avviket er "
          "forklart.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
