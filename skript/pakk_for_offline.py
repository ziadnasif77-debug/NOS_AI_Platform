"""
PAKKING FOR OFFLINE-SERVER — kjøres på DENNE (nett-tilkoblede) maskinen.

Samler ALT det lokale dokument-API-et trenger i én mappe som kan
kopieres til en server UTEN internett:

  offline_pakke/
    wheels/              alle pip-hjul (inkl. torch CUDA + transitive)
    easyocr_modeller/    EasyOCR sine auto-nedlastede modeller
    krav_lokal.txt       kopi av kravfila
    MANIFEST.txt         hva som ble pakket + miljøet det ble bygget på
    installer_offline.py + sjekk_miljo.py (kopieres inn)

Bruk (fra D:\\nav):
    python skript/pakk_for_offline.py

Deretter: kopier HELE offline_pakke/ + prosjektmappen + modeller/ til
serveren, og kjør installer_offline.py der. Se docs/offline_installasjon.md.
"""
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROT = Path(__file__).resolve().parent.parent
PAKKE = ROT / "offline_pakke"
WHEELS = PAKKE / "wheels"
KRAV = ROT / "krav_lokal.txt"

TORCH_INDEKS = "https://download.pytorch.org/whl/cu124"
LLAMA_INDEKS = "https://abetlen.github.io/llama-cpp-python/whl/cu124"

# Hjul som må hentes fra egne indekser (ikke PyPI)
CUDA_PAKKER = {
    "torch==2.6.0+cu124": TORCH_INDEKS,
    "torchvision==0.21.0+cu124": TORCH_INDEKS,
}


def _kjor(args):
    print("  $", " ".join(args))
    r = subprocess.run(args)
    if r.returncode != 0:
        raise SystemExit(f"\n!!! Kommando feilet ({r.returncode}). Avbryter — "
                         "pakken ville blitt ufullstendig.")


def _last_ned_hjul():
    WHEELS.mkdir(parents=True, exist_ok=True)
    py = sys.executable

    # 1) pip/setuptools/wheel selv — i tilfelle serverens pip er gammel
    _kjor([py, "-m", "pip", "download", "-d", str(WHEELS),
           "pip", "setuptools", "wheel"])

    # 2) torch + torchvision (CUDA 12.4) fra PyTorch-indeksen
    _kjor([py, "-m", "pip", "download", "-d", str(WHEELS),
           "--index-url", TORCH_INDEKS,
           "torch==2.6.0+cu124", "torchvision==0.21.0+cu124"])

    # 3) llama-cpp-python (CUDA-hjul) fra abetlen + PyPI for avhengigheter
    _kjor([py, "-m", "pip", "download", "-d", str(WHEELS),
           "--extra-index-url", LLAMA_INDEKS,
           "llama-cpp-python==0.3.34"])

    # 4) resten fra PyPI (torch er alt hentet, så -r finner det lokalt).
    #    --find-links lar pip gjenbruke allerede nedlastede CUDA-hjul.
    _kjor([py, "-m", "pip", "download", "-d", str(WHEELS),
           "--find-links", str(WHEELS),
           "--extra-index-url", LLAMA_INDEKS,
           "-r", str(KRAV)])


def _easyocr_kilde():
    """Hvor EasyOCR-vektene FAKTISK ligger.

    Portabilitetsvakten setter EASYOCR_MODULE_PATH til nav/.EasyOCR, så
    det er der de havner på en riktig oppsatt maskin. Brukerprofilen
    sjekkes som fallback for maskiner satt opp før vakten kom — men
    prosjektmappa har forrang, ellers pakker vi vekter fra feil sted."""
    for kandidat in (ROT / ".EasyOCR" / "model",
                     Path.home() / ".EasyOCR" / "model"):
        if kandidat.is_dir() and any(kandidat.glob("*.pth")):
            return kandidat
    return None


def _kopier_easyocr():
    kilde = _easyocr_kilde()
    mal = PAKKE / "easyocr_modeller"
    if kilde is None:
        print("\n  ADVARSEL: EasyOCR-modeller ikke funnet — verken i "
              f"{ROT / '.EasyOCR' / 'model'} eller ~/.EasyOCR/model.")
        print("  Kjør en OCR én gang på denne maskinen først (så lastes de ned),")
        print("  og kjør dette skriptet på nytt. Uten dem feiler OCR offline.\n")
        return 0
    print(f"  Fant EasyOCR-modeller i {kilde}")
    mal.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in kilde.glob("*.pth"):
        shutil.copy2(f, mal / f.name)
        n += 1
    print(f"  Kopierte {n} EasyOCR-modeller ({sum(f.stat().st_size for f in mal.glob('*.pth'))//1024//1024} MB)")
    return n


def _kopier_skript():
    for navn in ("installer_offline.py", "sjekk_miljo.py"):
        kilde = ROT / "skript" / navn
        if kilde.is_file():
            shutil.copy2(kilde, PAKKE / navn)
    shutil.copy2(KRAV, PAKKE / "krav_lokal.txt")


def _skriv_manifest(antall_easyocr):
    import platform
    hjul = sorted(f.name for f in WHEELS.glob("*"))
    linjer = [
        "OFFLINE-PAKKE FOR NAV DOKUMENT-API",
        "=" * 50,
        f"Bygget på: {platform.platform()}",
        f"Python:    {sys.version.split()[0]} ({platform.machine()})",
        f"Antall hjul: {len(hjul)}",
        f"EasyOCR-modeller: {antall_easyocr}",
        "",
        "MÅL-SERVER MÅ VÆRE: Windows x64 + Python 3.11 (samme som over).",
        "Andre plattformer/Python-versjoner → hjulene passer IKKE.",
        "",
        "GPU: torch er CUDA 12.4-utgave. Serveren trenger NVIDIA-driver",
        "som støtter CUDA 12.4 (driver >= 550). sjekk_miljo.py verifiserer.",
        "",
        "Installer på serveren:  python installer_offline.py",
        "",
        "--- HJUL ---",
        *hjul,
    ]
    (PAKKE / "MANIFEST.txt").write_text("\n".join(linjer), encoding="utf-8")
    print(f"\n  MANIFEST.txt skrevet ({len(hjul)} hjul).")


def _skriv_kontrollsummer():
    """§23 vil ha `/checksums` og `release-manifest.json` i bunten; §26
    vil at installasjonen skal være «checksum-verifisert».

    Skrives HER, som siste steg i pakkingen, slik at en bunt aldri kan
    bli til uten dem. Var det et eget skript man måtte huske å kjøre,
    ville den første bunten noen laget i en fart vært uten."""
    sys.path.insert(0, str(ROT))
    from delt import kontrollsummer
    m = kontrollsummer.lag(str(PAKKE))
    print(f"      {m['antall_filer']} filer, "
          f"{m['sum_bytes'] // 1024 // 1024} MB — SHA256SUMS + "
          f"release-manifest.json skrevet")


def main():
    print("=" * 60)
    print("  PAKKER DET LOKALE DOKUMENT-API-ET FOR OFFLINE-SERVER")
    print("=" * 60)
    if not KRAV.is_file():
        raise SystemExit(f"Fant ikke {KRAV}")
    print("\n[1/4] Laster ned alle pip-hjul (dette tar noen minutter) ...")
    _last_ned_hjul()
    print("\n[2/4] Kopierer EasyOCR-modeller ...")
    n = _kopier_easyocr()
    print("\n[3/4] Kopierer installasjons- og sjekkeskript ...")
    _kopier_skript()
    print("\n[4/5] Skriver manifest ...")
    _skriv_manifest(n)
    print("\n[5/5] Regner kontrollsummer (leser hver fil helt) ...")
    _skriv_kontrollsummer()
    storrelse = sum(f.stat().st_size for f in PAKKE.rglob("*") if f.is_file())
    print("\n" + "=" * 60)
    print(f"  FERDIG. offline_pakke/ = {storrelse//1024//1024} MB")
    print("=" * 60)
    print(f"  Mappe: {PAKKE}")
    print("  Kopier denne mappen + hele prosjektet + modeller/ til serveren.")
    print("  På serveren:  python installer_offline.py")


if __name__ == "__main__":
    main()
