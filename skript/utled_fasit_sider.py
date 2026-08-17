"""
Utleder `fasit_sider` for spørsmålskorpuset — hvilke sider beviset står på.

    .pyruntime\\python.exe skript\\utled_fasit_sider.py            # vis
    .pyruntime\\python.exe skript\\utled_fasit_sider.py --skriv    # lagre

§13.1 krever `candidate_precision` og `candidate_recall` for Evidence
Selection. Ingen av dem kan regnes uten å vite hvilke sider svaret
FAKTISK står på — og det sto ikke i korpuset.

HVORFOR UTLEDET OG IKKE HÅNDSKREVET
Fasiten finnes allerede: korpuset retter svar mot `maa_inneholde` og
`ett_av`. De samme strengene sier hvor beviset står — de er jo nettopp
det som må finnes i et riktig svar. Å skrive 133 sidelister for hånd
ville gitt en ANDRE fasit ved siden av den første, og to fasiter for
samme sak går fra hverandre. Her leses den ene som finnes.

NEGATIVE SPØRSMÅL FÅR TOM LISTE
De 12 spørsmålene av typen `negativ` spør om noe som IKKE står i
dokumentet. Deres godtatte former er ord som «ikke» og «ingen», som står
overalt — så et tekstsøk ville pekt på halve bunken. Fasiten deres er at
det ikke finnes noen side, og det er en tom liste, ikke en manglende.

DET UTLEDNINGEN IKKE KAN
Et treff betyr «strengen står her», ikke «beviset er her». Står
«4417820» både i vedtaket og i fakturaen, får begge sider — og det er
riktig for recall, men gjør precision mildere enn en menneskelig fasit
ville gjort. Det skal stå i rapporten, ikke oppdages i ettertid.
"""
import argparse
import json
import os
import re
import sys

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                               # noqa: BLE001
    pass

KORPUS = os.path.join(ROT, "tester", "korpus",
                      "sporsmaal_syntetisk_bunke.json")
BUNKE = os.path.join(ROT, "data", "korpus", "syntetisk_bunke_tekstlag.pdf")


def _normaliser(tekst: str) -> str:
    """Samme normalisering som korpuskjøreren bruker når den retter:
    små bokstaver, æøå foldet, og mellomrom inne i tall fjernet («45 310»
    og «45310» er samme beløp)."""
    t = (tekst or "").lower()
    for fra, til in (("æ", "ae"), ("ø", "oe"), ("å", "aa"),
                     (" ", " ")):
        t = t.replace(fra, til)
    t = re.sub(r"(?<=\d)[ .](?=\d)", "", t)
    return re.sub(r"\s+", " ", t)


def sidetekster() -> dict:
    import fitz
    d = fitz.open(BUNKE)
    ut = {i + 1: _normaliser(d[i].get_text() or "")
          for i in range(d.page_count)}
    d.close()
    return ut


def sider_for(sp: dict, sider: dict):
    """Sidene som inneholder beviset — eller None når det ikke lot seg
    utlede.

    Skillet er det samme som resten av prosjektet bruker (R128): `[]` er
    en PÅSTAND — det finnes ingen side, og det er riktig svar. `None`
    betyr at utledningen ikke klarte det, og da skal spørsmålet holdes
    UTENFOR precision/recall i stedet for å telle som en tom fasit.

    Uten det skillet ville 18 spørsmål med utregnede summer («129 dager»
    står ingen steder ordrett) sett ut som negative spørsmål, og
    Evidence Selection ville fått straff for å velge sider den SKULLE
    valgt."""
    if sp.get("type") == "negativ":
        return []                       # svaret finnes ikke — med vilje
    biter = list(sp.get("maa_inneholde") or [])
    if not biter:
        # `ett_av` er alternative FORMER av samme svar (dato med punktum
        # eller bindestrek). Én form som treffer er nok.
        biter = list(sp.get("ett_av") or [])
    treff = set()
    for nr, tekst in sider.items():
        for bit in biter:
            b = _normaliser(str(bit))
            if len(b) >= 3 and b in tekst:
                treff.add(nr)
                break
    if not treff:
        return None                 # ikke utledbart — ikke «ingen side»
    # Treffer fasiten over halve bunken, skiller den ingenting og duger
    # ikke som fasit for presisjon (typisk et årstall eller et ord som
    # står i hver sidefot).
    if len(treff) > len(sider) / 2:
        return None
    return sorted(treff)


def main() -> int:
    p = argparse.ArgumentParser(description="Utled fasit_sider (§13.1)")
    p.add_argument("--skriv", action="store_true",
                   help="lagre i korpusfila (uten dette bare vises det)")
    args = p.parse_args()

    korpus = json.load(open(KORPUS, encoding="utf-8"))
    sider = sidetekster()
    print(f"  Bunke: {len(sider)} sider   Spørsmål: "
          f"{len(korpus['sporsmaal'])}\n")

    uten, negative, med = [], 0, 0
    for sp in korpus["sporsmaal"]:
        f = sider_for(sp, sider)
        sp["fasit_sider"] = f
        if f is None:
            uten.append(sp["id"])
        elif not f:
            negative += 1
        else:
            med += 1

    print(f"  Med sider (teller i KPI-ene) : {med}")
    print(f"  Negative, [] med vilje       : {negative}")
    print(f"  Ikke utledbart, null         : {len(uten)}")
    if uten:
        print("\n  Disse holdes UTENFOR precision/recall. Svaret står ikke")
        print("  ordrett på noen side (utregnede summer, omskrevne svar,")
        print("  spørsmål om dokumentets struktur), eller fasiten traff")
        print("  over halve bunken og skiller da ingenting:")
        for i in uten:
            print(f"      {i}")

    fordeling = {}
    for sp in korpus["sporsmaal"]:
        f = sp["fasit_sider"]
        m = "null" if f is None else len(f)
        fordeling[m] = fordeling.get(m, 0) + 1
    print("\n  Sider per spørsmål  : "
          + ", ".join(f"{k}: {v}" for k, v in
                      sorted(fordeling.items(), key=lambda x: str(x[0]))))

    if args.skriv:
        korpus["fasit_sider_utledet_av"] = (
            "skript/utled_fasit_sider.py — sidene der maa_inneholde/ett_av "
            "står ordrett. [] = det finnes ingen side (negative spørsmål). "
            "null = lot seg ikke utlede, og spørsmålet holdes utenfor "
            "precision/recall. Et treff betyr «strengen står her», ikke "
            "«beviset er her»: står samme tall i to dokumenter, får begge "
            "sider — mildere mot presisjon enn en menneskelig fasit.")
        with open(KORPUS, "w", encoding="utf-8") as f:
            json.dump(korpus, f, ensure_ascii=False, indent=2)
        print(f"\n  Lagret i {os.path.relpath(KORPUS, ROT)}")
    else:
        print("\n  (ingenting lagret — kjør med --skriv)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
