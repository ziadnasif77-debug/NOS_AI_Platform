"""
OFFLINE-INSTALLASJON — kjøres på SERVEREN (uten internett).

Installerer alle pip-hjul fra offline_pakke/wheels/ uten å røre nettet,
legger EasyOCR-modellene på plass, og kjører til slutt full miljøsjekk.

Forutsetning: offline_pakke/ ligger ved siden av dette skriptet (slik
pakk_for_offline.py la det), og prosjektmappen + modeller/ er kopiert
til serveren.

Bruk (fra mappen der offline_pakke/ ligger, ELLER fra prosjektroten):
    python installer_offline.py
"""
import io
import shutil
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HER = Path(__file__).resolve().parent
# Prosjektroten (nav/). ALT som installeres skal havne her, aldri i en
# brukerprofil — se CLAUDE.md §1.
ROT = HER.parent
# offline_pakke kan være HER selv, eller en undermappe
PAKKE = HER if (HER / "wheels").is_dir() else HER / "offline_pakke"
WHEELS = PAKKE / "wheels"
KRAV = PAKKE / "krav_lokal.txt"


def main():
    print("=" * 60)
    print("  OFFLINE-INSTALLASJON — NAV lokalt dokument-API")
    print("=" * 60)
    if not WHEELS.is_dir():
        raise SystemExit(f"Fant ikke wheels-mappen: {WHEELS}\n"
                         "Kjør fra samme sted som offline_pakke/ ligger.")
    if not KRAV.is_file():
        raise SystemExit(f"Fant ikke {KRAV}")

    py = sys.executable
    print(f"\n[1/3] Installerer hjul fra {WHEELS} (uten nett) ...")
    # Oppgrader pip/setuptools/wheel først, deretter alt fra kravfila.
    # --no-index = rør ALDRI nettet; --find-links = bruk kun lokal mappe.
    subprocess.run([py, "-m", "pip", "install", "--no-index",
                    "--find-links", str(WHEELS),
                    "pip", "setuptools", "wheel"], check=False)
    r = subprocess.run([py, "-m", "pip", "install", "--no-index",
                        "--find-links", str(WHEELS), "-r", str(KRAV)])
    if r.returncode != 0:
        raise SystemExit("\n!!! pip-installasjon feilet. Se feilen over. "
                         "Vanligste årsak: server-plattform/Python-versjon "
                         "matcher ikke maskinen pakken ble bygd på.")

    print("\n[2/3] Legger EasyOCR-modeller på plass ...")
    kilde = PAKKE / "easyocr_modeller"
    # INNE i prosjektet (CLAUDE.md §1). Målet var Path.home()/.EasyOCR —
    # altså brukerprofilen — men portabilitetsvakten setter
    # EASYOCR_MODULE_PATH til nav/.EasyOCR, så serveren lette et helt
    # annet sted enn installasjonen la vektene. På en fersk offline
    # server ga det OCR som feilet uten at noe pekte på hvorfor.
    mal = ROT / ".EasyOCR" / "model"
    if kilde.is_dir() and any(kilde.glob("*.pth")):
        mal.mkdir(parents=True, exist_ok=True)
        for f in kilde.glob("*.pth"):
            shutil.copy2(f, mal / f.name)
        print(f"  Kopierte EasyOCR-modeller til {mal}")
    else:
        print("  ADVARSEL: ingen EasyOCR-modeller i pakken — OCR vil feile "
              "offline. Se pakk_for_offline.py.")

    print("\n[3/3] Kjører miljøsjekk ...\n")
    sjekk = HER / "sjekk_miljo.py"
    if not sjekk.is_file():
        # sjekk_miljo ligger normalt i skript/ i prosjektet
        prosjekt_sjekk = PAKKE.parent / "skript" / "sjekk_miljo.py"
        sjekk = prosjekt_sjekk if prosjekt_sjekk.is_file() else PAKKE / "sjekk_miljo.py"
    subprocess.run([py, str(sjekk)])


if __name__ == "__main__":
    main()
