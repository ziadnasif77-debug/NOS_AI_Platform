"""
rydd_gjennomgang.py — sletter GAMLE gjennomgangsbilder etter et
oppbevaringsvindu. Gjennomgangsmappa (GJENNOMGANG_STI/bilder/) er det
ENESTE stedet systemet bevarer data midlertidig (bildekopi + rå tekst
sendt til Label Studio for korreksjon), så dette er GDPR-hygiene for
sensitive dokumenter.

TRYGG SOM STANDARD:
  python skript/rydd_gjennomgang.py            # TØRRKJØRING — viser bare hva
  python skript/rydd_gjennomgang.py --slett    # sletter faktisk

Vindu: OPPBEVARING_DAGER (standard 30). Dette er en GOVERNANCE-beslutning
(§6.4), ikke en teknisk default — sett din egen policy. Vinduet bør være
lengre enn den vanlige gjennomgangs-turnarounden, ellers kan et bilde
slettes mens en oppgave fortsatt venter på korreksjon.

MERK: dette rydder de lokale BILDEKOPIENE. Sletting av selve
Label Studio-oppgavene (og bare etter at korreksjonen er hentet inn i
trening) er et separat, LS-status-avhengig steg — se README.
"""
import os
import sys
import time
from pathlib import Path

GJENNOMGANG_STI = os.environ.get("GJENNOMGANG_STI", "./data/gjennomgang")
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


def rydd(slett: bool, naa: float = None) -> int:
    """Rydder gamle gjennomgangsbilder. Returnerer antall (potensielt)
    slettede. slett=False = tørrkjøring (sletter ingenting)."""
    naa = time.time() if naa is None else naa
    bilder = Path(GJENNOMGANG_STI) / "bilder"
    if not bilder.exists():
        print(f"Ingen gjennomgangsmappe ({bilder}) — ingenting å rydde.")
        return 0

    gamle = finn_gamle(bilder, OPPBEVARING_DAGER, naa)
    total_mb = sum(p.stat().st_size for p in gamle if p.exists()) / 1e6
    print(f"{len(gamle)} filer eldre enn {OPPBEVARING_DAGER} dager "
          f"({total_mb:.1f} MB) i {bilder}")
    if not gamle:
        return 0

    if not slett:
        for p in gamle[:10]:
            print(f"  ville slettet: {p.name}")
        if len(gamle) > 10:
            print(f"  … og {len(gamle) - 10} til")
        print("TØRRKJØRING — ingenting slettet. Legg til --slett for å slette.")
        return len(gamle)

    slettet = 0
    for p in gamle:
        try:
            p.unlink()
            slettet += 1
        except OSError as feil:
            print(f"  kunne ikke slette {p.name}: {feil}")
    print(f"Slettet {slettet} av {len(gamle)} filer.")
    return slettet


if __name__ == "__main__":
    rydd("--slett" in sys.argv)
