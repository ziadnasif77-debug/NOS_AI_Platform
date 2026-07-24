"""
Motoravtrykk: oppdager i det stille byttede OCR-/LLM-motorer.

norhand har full automatikk (grunnmodell.json → automatisk retrening av
korreksjonsarkivet). De ANDRE motorene har ingen lært tilstand å retrene —
men hele terskelkaskaden (velg_motor-grensene, LS_KONFIDENS_TERSKEL=0.85,
UFCN-tersklene, VRAM-budsjettet BOREALIS_KONTEKST=4096/2600/1500 MB) er
KALIBRERT mot konfidensfordelingen til akkurat dagens vektfiler. Byttes en
motor (ny EasyOCR-nedlasting, pip-oppgradering av rapidocr, ny GGUF, nye
Doc-UFCN-vekter), skifter fordelingen — og feilruting/feiltriggere er
USYNLIGE i drift (beam-fiksen 2026-07-23 beviste hvor mye en stille
skalaendring skjevvrir arbitreringen).

Derfor: avtrykk (størrelse + sha256 av første MB) av hver motors vektfiler
huskes i data/finjustering/motoravtrykk.json. Ved avvik ropes det høyt i
serverloggen ved HVER oppstart — til noen bevisst godtar de nye vektene:

  python -m delt.motoravtrykk           # vis status
  python -m delt.motoravtrykk --godta   # godta nåværende vekter som kjent
"""
import json
import os
import hashlib
from pathlib import Path

AVTRYKK_STI = (Path(os.environ.get("FINJUSTERING_STI", "./data/finjustering"))
               / "motoravtrykk.json")


def _avtrykk(sti: Path) -> str:
    """Samme algoritme som valider_modell.modell_avtrykk: størrelse +
    sha256 av første megabyte — billig, men skiller modellutgaver sikkert."""
    try:
        h = hashlib.sha256()
        h.update(str(sti.stat().st_size).encode())
        with open(sti, "rb") as f:
            h.update(f.read(1024 * 1024))
        return h.hexdigest()[:16]
    except OSError:
        return "ukjent"


def _motorfiler() -> dict:
    """Vektfilene per motor. norhand er BEVISST utelatt — den har sin egen,
    sterkere mekanisme (grunnmodell.json + automatisk retrening)."""
    modeller = Path(os.environ.get("MODELLER_STI", "./modeller"))
    easyocr = Path(os.environ.get("EASYOCR_MODULE_PATH", "./.EasyOCR"))
    motorer = {
        "easyocr": sorted((easyocr / "model").glob("*.pth")),
        "doc-ufcn": [modeller / "doc-ufcn-norhand" / "model.pth"],
        "borealis": sorted((modeller / "borealis-gguf").glob("*.gguf")),
    }
    try:
        import rapidocr
        motorer["rapidocr"] = sorted(
            (Path(rapidocr.__file__).parent / "models").glob("*.onnx"))
    except ImportError:
        motorer["rapidocr"] = []
    return motorer


def _naavaerende() -> dict:
    return {motor: {fil.name: _avtrykk(fil) for fil in filer if fil.is_file()}
            for motor, filer in _motorfiler().items()}


def _kjente() -> dict:
    try:
        return json.loads(AVTRYKK_STI.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def godta() -> None:
    """Registrer nåværende vekter som kjente (stilner advarslene)."""
    AVTRYKK_STI.parent.mkdir(parents=True, exist_ok=True)
    AVTRYKK_STI.write_text(
        json.dumps(_naavaerende(), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")


def sjekk(logg=print) -> list:
    """Sammenlign nåværende vekter med kjente. Returnerer avvikslisten
    (tom = alt i orden). Første gang (ingenting kjent) registreres dagens
    vekter stille som utgangspunkt. NYE filer registreres stille (utvidelse
    er ufarlig) — bare ENDREDE og FJERNEDE vektfiler varsles, hver oppstart,
    til noen bevisst godtar dem med «python -m delt.motoravtrykk --godta»."""
    naa = _naavaerende()
    kjent = _kjente()
    if not kjent:
        godta()
        return []

    avvik = []
    for motor, filer in naa.items():
        kjente_filer = kjent.get(motor, {})
        for navn, avtrykk in filer.items():
            gammelt = kjente_filer.get(navn)
            if gammelt is None:
                kjente_filer[navn] = avtrykk      # ny fil: registrer stille
            elif avtrykk != gammelt:
                # ASCII-pil: loggen skal tåle cp1252/cp1256-konsoller også
                avvik.append(f"{motor}/{navn}: ENDRET ({gammelt} -> {avtrykk})")
        for navn in kjente_filer:
            if navn not in filer:
                avvik.append(f"{motor}/{navn}: FJERNET")
    for motor in kjent:
        if motor not in naa:
            for navn in kjent[motor]:
                avvik.append(f"{motor}/{navn}: FJERNET")

    if avvik:
        logg("=" * 70)
        logg("ADVARSEL: motorvekter er BYTTET siden tersklene ble kalibrert!")
        for a in avvik:
            logg(f"  - {a}")
        logg("Konfidensterskler (velg_motor, LS-porten 0.85, UFCN, VRAM-"
             "budsjett) er kalibrert mot de GAMLE vektene — kontroller "
             "lesekvaliteten, og godta så de nye vektene med:")
        logg("  python -m delt.motoravtrykk --godta")
        logg("=" * 70)
    else:
        # stille registrering av evt. nye filer som kom til
        AVTRYKK_STI.parent.mkdir(parents=True, exist_ok=True)
        AVTRYKK_STI.write_text(
            json.dumps(naa, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8")
    return avvik


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if "--godta" in sys.argv:
        godta()
        print(f"Nåværende motorvekter registrert som kjente ({AVTRYKK_STI}).")
    else:
        avvik = sjekk()
        if not avvik:
            print("Alle motorvekter samsvarer med de kjente avtrykkene.")
