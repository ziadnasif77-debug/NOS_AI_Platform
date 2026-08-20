"""
Måler hvilke felter som faktisk lar seg PÅVISE per dokumenttype (R247).

    .pyruntime\\python.exe skript\\kjor_typeforventninger.py
    .pyruntime\\python.exe skript\\kjor_typeforventninger.py --type purring

Bakgrunnen: R241 innførte elleve nye dokumenttyper, og de fikk med vilje
ingen forventninger i `delt/typeforventninger.py`. Begrunnelsen sto i
modulen selv — «bare det som er tilnærmet sikkert for typen» — og vi
hadde ikke målt hva som er sikkert. En forventning uten måling roper
«mangler» på friske dokumenter, og et felt som roper ulv slutter å bli
lest.

Dette skriptet er målingen. Det kjører det deterministiske uttrekket over
`tester/korpus/typevarianter.json` og teller, per type og felt, hvor
mange varianter feltet ble påvist i.

REGELEN SOM FØLGER AV TALLENE
Bare felter påvist i ALLE variantene av typen kan bli en forventning.
Ett bomskudd er nok til å diskvalifisere: da finnes det et ekte dokument
av typen som ville fått en falsk «mangler».

HVA MÅLINGEN IKKE ER
Korpuset er syntetisk og skrevet av oss. Den svakheten skal sies høyt:
måler vi bare på varianter vi selv fant på, måler vi våre egne
antakelser. Motgiften er «knapp»-varianten — et magert, men helt ekte
dokument av samme type — som er skrevet nettopp for å FALSIFISERE
antakelsene. Et felt som overlever den, er kandidat; alle andre er det
ikke.

Når et ekte arkiv finnes, er dette skriptet stedet å kjøre det gjennom.
Tallene erstatter da disse, og FORVENTNINGER oppdateres etter dem — ikke
etter en mening.
"""
import argparse
import json
import os
import sys

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "tester"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                               # noqa: BLE001
    pass

from delt.tekstuttrekk import gjett_dokumenttype, strukturert_uttrekk
from delt.typeforventninger import FELTDETEKTORER, FORVENTNINGER
from syntetiske_nummer import lag_fnr

KORPUS = os.path.join(ROT, "tester", "korpus", "typevarianter.json")

# Felter som treffer i alle varianter, men som IKKE kan brukes som
# forventning fordi de ikke kan slå ut på noe ekte.
#
# `tittel` er målt: detektoren er `False` bare når teksten er HELT tom —
# «bare feltlinjer» og «uten dato» gir begge tittel. Et tomt dokument er
# alt fanget av tomside-vakten og forhåndssjekken, så en forventning om
# tittel ville aldri meldt noe nytt; den ville bare blåst opp «funnet».
# Til sammenligning er `dato` `False` for et ekte, gjenkjennelig
# dokument uten dato — den KAN altså melde noe. Ingen av de sytten eldre
# typene forventer tittel heller, av samme grunn.
IKKE_DISKRIMINERENDE = {"tittel"}


def les_korpus() -> list:
    """Dokumentene med fødselsnumrene satt inn på kjøretid.

    Numrene står ALDRI i fila: et ellevesifret tall ser ekte ut for den
    som leser repoet, og portabilitetsvakten stopper det uansett."""
    with open(KORPUS, encoding="utf-8") as f:
        raa = json.load(f)
    fnr, fnr2 = lag_fnr(), lag_fnr(1)
    ut = []
    for d in raa["dokumenter"]:
        ut.append({**d, "tekst": d["tekst"].replace("{FNR2}", fnr2)
                                           .replace("{FNR}", fnr)})
    return ut


def maal(dokumenter: list) -> dict:
    """{type: {felt: (treff, totalt)}} — pluss klassifiseringsfasit."""
    per_type = {}
    for d in dokumenter:
        bok = per_type.setdefault(d["type"], {
            "totalt": 0, "felt": {}, "feilklassifisert": []})
        bok["totalt"] += 1
        # Klassifiseringen MÅ stemme, ellers måler vi feil type sine felt
        faktisk = gjett_dokumenttype(d["tekst"]) or "(ingen)"
        if faktisk != d["type"]:
            bok["feilklassifisert"].append(f"{d['variant']} → {faktisk}")
        struktur = strukturert_uttrekk(d["tekst"])
        for felt, detektor in FELTDETEKTORER.items():
            if detektor(struktur):
                bok["felt"][felt] = bok["felt"].get(felt, 0) + 1
    return per_type


def skriv(per_type: dict, bare=None) -> int:
    felter = sorted(FELTDETEKTORER)
    bredde = max(len(f) for f in felter)
    avvik = 0
    print("=" * 72)
    print("MÅLTE FELTER PER DOKUMENTTYPE — «x/y» = påvist i x av y varianter")
    print("=" * 72)
    for type_ in sorted(per_type):
        if bare and type_ != bare:
            continue
        bok = per_type[type_]
        n = bok["totalt"]
        sikre = sorted(f for f in felter
                       if bok["felt"].get(f, 0) == n
                       and f not in IKKE_DISKRIMINERENDE)
        print(f"\n{type_}  ({n} varianter)")
        if bok["feilklassifisert"]:
            avvik += len(bok["feilklassifisert"])
            print(f"  !! FEILKLASSIFISERT: "
                  f"{', '.join(bok['feilklassifisert'])}")
        for felt in felter:
            treff = bok["felt"].get(felt, 0)
            if not treff:
                continue
            if treff != n:
                merke = ""
            elif felt in IKKE_DISKRIMINERENDE:
                merke = "  (treffer alltid — ikke brukbar)"
            else:
                merke = "  <- kandidat"
            print(f"    {felt:{bredde}}  {treff}/{n}{merke}")
        naa = FORVENTNINGER.get(type_)
        print(f"    kandidater : {', '.join(sikre) or '(ingen)'}")
        print(f"    i koden nå : "
              f"{', '.join(naa) if naa else '(ingen forventninger)'}")
        if tuple(sikre) != tuple(naa or ()):
            avvik += 1
            print("    ** AVVIK mellom måling og kode **")
    print("\n" + "=" * 72)
    print(f"{'ALT I TAKT' if not avvik else f'{avvik} avvik'} — "
          f"{len(per_type)} typer målt")
    return avvik


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--type", help="mål bare denne dokumenttypen")
    args = p.parse_args()
    return 0 if skriv(maal(les_korpus()), args.type) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
