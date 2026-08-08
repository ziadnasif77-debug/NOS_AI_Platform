# -*- coding: utf-8 -*-
"""Sletter alle spor av ETT dokument fra korreksjonsarkivet (GDPR art. 17).

    python skript/slett_person.py <kilde_dokument>            # tørrkjøring
    python skript/slett_person.py <kilde_dokument> --slett    # utfør
    python skript/slett_person.py --list                      # hva finnes?

HVORFOR DETTE SKRIPTET FINNES
`data/finjustering/` er dokumentert som permanent — «slettes aldri
automatisk». Det er et forsvarlig valg for et treningsarkiv, men det er
bare forsvarlig hvis sletting er MULIG når noen ber om det.

Før dette var den ikke det. Radene hadde `fil_sti`, `tekst`,
`oppgave_id` og `annotert_av` — ingen nøkkel tilbake til dokumentet
rettingen kom fra. Svaret på «slett opplysningene mine» var da i
praksis «vi finner dem ikke», uansett hva en policy måtte si. En
rettighet som ikke kan utøves teknisk, er ikke en rettighet (R172).

`kilde_dokument` fylles av `eksporter_fra_label_studio.py`. Rader
eksportert FØR det feltet fantes, har det ikke — de listes for seg av
`--list`, og må håndteres manuelt. Det er en ærlig grense, ikke en
skjult en.

HVA SOM SLETTES
  * radene i data/finjustering/trocr_*.json
  * bildene de peker på i data/finjustering/bilder/
  * en tom trocr-fil fjernes helt

HVA SOM IKKE SLETTES — OG HVORFOR
Modellvektene i `modeller/norhand/`. Kunnskap trukket ut av et
datasett kan ikke fjernes fra vektene uten å trene på nytt. Er det et
krav, må modellen retrenes fra et arkiv der radene alt er borte —
altså: kjør dette skriptet FØRST, så `make finjuster`. Skriptet sier
fra om dette hver gang, for det er den delen folk glemmer.
"""
import io
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINJUSTERING_STI = os.environ.get(
    "FINJUSTERING_STI", os.path.join(ROT, "data", "finjustering"))


def _filer() -> list:
    return sorted(Path(FINJUSTERING_STI).glob("trocr_*.json"))


def _les(fil: Path) -> list:
    try:
        return json.loads(fil.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def oversikt() -> dict:
    """{kilde: antall rader} — pluss hvor mange som mangler nøkkelen."""
    kilder, uten = {}, 0
    for fil in _filer():
        for rad in _les(fil):
            nokkel = rad.get("kilde_dokument")
            if nokkel:
                kilder[nokkel] = kilder.get(nokkel, 0) + 1
            else:
                uten += 1
    return {"kilder": kilder, "uten_nokkel": uten}


def slett(kilde: str, utfor: bool) -> dict:
    """Fjerner alle rader med `kilde_dokument == kilde`, og bildene."""
    svar = {"rader": 0, "bilder": 0, "filer_tomme": 0,
            "torrkjoring": not utfor, "kilde": kilde}
    for fil in _filer():
        rader = _les(fil)
        beholdt = [r for r in rader if r.get("kilde_dokument") != kilde]
        traff = [r for r in rader if r.get("kilde_dokument") == kilde]
        if not traff:
            continue
        svar["rader"] += len(traff)
        for rad in traff:
            sti = rad.get("fil_sti") or ""
            if sti and os.path.isfile(sti):
                svar["bilder"] += 1
                if utfor:
                    try:
                        os.remove(sti)
                    except OSError as exc:
                        print(f"  kunne ikke slette {sti}: "
                              f"{type(exc).__name__}", file=sys.stderr)
        if not utfor:
            continue
        if beholdt:
            # Atomisk, som ellers i prosjektet: en halvskrevet
            # arkivfil er verre enn ingen sletting.
            midl = str(fil) + ".ny"
            with io.open(midl, "w", encoding="utf-8", newline="\n") as f:
                json.dump(beholdt, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(midl, str(fil))
        else:
            os.remove(str(fil))
            svar["filer_tomme"] += 1
    return svar


def main() -> int:
    args = sys.argv[1:]
    if not args or "--list" in args:
        o = oversikt()
        if not o["kilder"] and not o["uten_nokkel"]:
            print("Arkivet er tomt.")
            return 0
        print(f"Kilder i {FINJUSTERING_STI}:")
        for kilde, antall in sorted(o["kilder"].items()):
            print(f"  {kilde:40} {antall} rad(er)")
        if o["uten_nokkel"]:
            print()
            print(f"  {o['uten_nokkel']} rad(er) UTEN `kilde_dokument` — "
                  "eksportert før feltet fantes.")
            print("  De kan ikke slettes selektivt av dette skriptet og må "
                  "håndteres manuelt.")
        return 0

    kilde = args[0]
    utfor = "--slett" in args
    svar = slett(kilde, utfor)
    if not svar["rader"]:
        print(f"Fant ingen rader for «{kilde}». Kjør --list for å se hva "
              f"som finnes.")
        return 1

    if svar["torrkjoring"]:
        print(f"TØRRKJØRING — ingenting er slettet.")
        print(f"  ville fjernet {svar['rader']} rad(er) og "
              f"{svar['bilder']} bilde(r) for «{kilde}»")
        print(f"  kjør på nytt med --slett for å utføre")
        return 1

    print(f"Slettet {svar['rader']} rad(er) og {svar['bilder']} bilde(r) "
          f"for «{kilde}».")
    if svar["filer_tomme"]:
        print(f"  {svar['filer_tomme']} tom(me) trocr-fil(er) fjernet")
    print()
    print("MERK: modellvektene i modeller/norhand/ er IKKE berørt.")
    print("Kunnskap trukket ut av et datasett kan ikke fjernes fra vekter")
    print("uten å trene på nytt. Kreves det, kjør `make finjuster` nå — ")
    print("arkivet er allerede renset, så den nye modellen bygges uten")
    print("disse radene.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
