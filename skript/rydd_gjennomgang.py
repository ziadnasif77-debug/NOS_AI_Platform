"""
rydd_gjennomgang.py — sletter GAMLE gjennomgangsbilder etter et
oppbevaringsvindu. Gjennomgangsmappa (GJENNOMGANG_STI/bilder/) bevarer
en bildekopi av side 1 og rå tekst sendt til Label Studio for
korreksjon, så dette er GDPR-hygiene for sensitive dokumenter.

MERK: dette er IKKE det eneste stedet systemet bevarer data — den
påstanden sto her tidligere og var feil. Systemet lagrer også:

  data/jobber/*.json   hele dokumentteksten per bakgrunnsjobb.
                       Ryddes av dokument_api.rydd_jobber() ved
                       oppstart og etter hver fullførte jobb
                       (JOBB_OPPBEVARING_DAGER, standard 30).
  data/logger/*.log    tilgangslogg med IP-adresser. Roterer
                       (RotatingFileHandler, 10 MB × 12).
  data/midlertidig/    side-1-bilder på vei til gjennomgang; slettes
                       normalt straks, men overlever et prosesskrasj.
  data/label-studio/   oppgavene selv, med rå tekst. Slettes IKKE av
                       dette skriptet — se «hva dette IKKE gjør».

En oppbevaringspolicy som ikke stemmer med virkeligheten er verre enn
ingen policy — derfor står hele lista her.

TRYGG SOM STANDARD:
  python skript/rydd_gjennomgang.py            # TØRRKJØRING — viser bare hva
  python skript/rydd_gjennomgang.py --slett    # sletter faktisk

EXITKODER (R158) — en policy som ikke ble utført skal ikke se ut som en
utført policy:
  0   ingenting forfalt, eller alt forfalt ble slettet
  1   noe var FORFALT og ble IKKE slettet (tørrkjøring)
  2   mappa fantes ikke — policyen ble ikke håndhevet i det hele tatt

Uten disse returnerte tørrkjøring og ekte sletting samme verdi, og
`__main__` kastet den. Et skript i Oppgaveplanleggeren med logg til fil
kunne dermed kjøre i månedsvis, skrive «ville slettet: …» hver uke, og
ingen hadde noe å varsle på.

Vindu: OPPBEVARING_DAGER (standard 30). Dette er en GOVERNANCE-beslutning
(§6.4), ikke en teknisk default — sett din egen policy. Vinduet bør være
lengre enn den vanlige gjennomgangs-turnarounden, ellers kan et bilde
slettes mens en oppgave fortsatt venter på korreksjon.

HVA DETTE IKKE GJØR
Sletting av selve Label Studio-oppgavene er et separat, LS-status-
avhengig steg. Det er IKKE implementert, og det står her fordi
alternativet er å la lesere tro at det er dekket: oppgavene bærer rå
tekst fra dokumentet og lever i `data/label-studio/` uten
oppbevaringsvindu.

Og korreksjonsarkivet (`data/finjustering/trocr_*.json`) PEKER inn i
mappa dette skriptet tømmer. Kjøres slettingen, mister treningsløkka
bildene den refererer til. Den avhengigheten må avklares før
`--slett` settes i drift — se `data/finjustering/README.md`.
"""
import os
import sys
import time
from pathlib import Path

# Konsollen på Windows er ikke UTF-8 som standard, og hver eneste
# melding her har æøå. Under omdirigering til en loggfil (cp1252/cp1256)
# kastet `print` UnicodeEncodeError FØR skriptet rakk å si hva det hadde
# gjort — og exitkoden ble 1 uansett utfall. Dette er den eneste fila i
# treningsløkka som manglet vakten (R158).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# Stien utledes fra PROSJEKTROTA, ikke fra arbeidsmappa. Docstringen
# anbefaler Oppgaveplanleggeren, og den starter i System32 — da pekte
# «./data/gjennomgang» et helt annet sted, mappa fantes ikke, og
# skriptet meldte «ingenting å rydde» med exitkode 0. En policy som
# rapporterer suksess fordi den leter på feil sted (CLAUDE.md §1).
ROT = Path(__file__).resolve().parent.parent
GJENNOMGANG_STI = os.environ.get("GJENNOMGANG_STI",
                                 str(ROT / "data" / "gjennomgang"))
OPPBEVARING_DAGER = int(os.environ.get("OPPBEVARING_DAGER", "30"))


def finn_gamle(mappe: Path, maks_alder_dager: int, naa: float) -> list:
    """Filer i mappe som er eldre enn vinduet (etter endringstid)."""
    grense = naa - maks_alder_dager * 86400
    gamle = []
    for p in mappe.glob("*"):
        if not p.is_file():
            continue
        try:
            if p.stat().st_mtime < grense:
                gamle.append(p)
        except OSError:
            continue
    return gamle


def rydd(slett: bool, naa: float = None) -> dict:
    """Rydder gamle gjennomgangsbilder.

    Returnerer {funnet, slettet, torrkjoring, mappe_mangler} — ikke ett
    tall. Tørrkjøring og ekte sletting returnerte tidligere SAMME verdi,
    så ingen kaller kunne skille «tre filer ble slettet» fra «tre filer
    er forfalt og står der fortsatt» (R158)."""
    naa = time.time() if naa is None else naa
    bilder = Path(GJENNOMGANG_STI) / "bilder"
    if not bilder.exists():
        print(f"Ingen gjennomgangsmappe ({bilder}) — ingenting å rydde.")
        return {"funnet": 0, "slettet": 0, "torrkjoring": not slett,
                "mappe_mangler": True}

    gamle = finn_gamle(bilder, OPPBEVARING_DAGER, naa)
    total_mb = sum(p.stat().st_size for p in gamle if p.exists()) / 1e6
    print(f"{len(gamle)} filer eldre enn {OPPBEVARING_DAGER} dager "
          f"({total_mb:.1f} MB) i {bilder}")
    svar = {"funnet": len(gamle), "slettet": 0, "torrkjoring": not slett,
            "mappe_mangler": False}
    if not gamle:
        return svar

    if not slett:
        for p in gamle[:10]:
            print(f"  ville slettet: {p.name}")
        if len(gamle) > 10:
            print(f"  … og {len(gamle) - 10} til")
        print("TØRRKJØRING — ingenting slettet. Legg til --slett for å slette.")
        return svar

    for p in gamle:
        try:
            p.unlink()
            svar["slettet"] += 1
        except OSError as feil:
            print(f"  kunne ikke slette {p.name}: {feil}")
    print(f"Slettet {svar['slettet']} av {len(gamle)} filer.")
    return svar


def _exitkode(svar: dict) -> int:
    """Utfallet som et tall en jobbplanlegger kan varsle på."""
    if svar["mappe_mangler"]:
        return 2
    if svar["torrkjoring"] and svar["funnet"]:
        return 1
    return 0


if __name__ == "__main__":
    r = rydd("--slett" in sys.argv)
    kode = _exitkode(r)
    if kode == 2:
        print("FEIL: fant ikke gjennomgangsmappa — INGEN oppbevaringspolicy "
              "ble håndhevet. Sjekk GJENNOMGANG_STI.", file=sys.stderr)
    elif kode == 1:
        print(f"ADVARSEL: {r['funnet']} filer er FORFALT og ble IKKE slettet "
              "(tørrkjøring). Kjør med --slett.", file=sys.stderr)
    sys.exit(kode)
