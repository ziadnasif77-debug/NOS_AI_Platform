"""
MILJØSJEKK — verifiserer at ALT det lokale dokument-API-et trenger er
på plass. Kjøres på serveren etter installasjon (og når som helst).

Sjekker, i rekkefølge: Python-versjon, alle kritiske importer, GPU/CUDA,
system-DLL-er (pyzbar/zbar), EasyOCR-modeller, Borealis-modellfiler, en
LITEN ekte kjøring (uttrekk fra en tekst), PORTABILITET (nav-lokal tolk,
buntet msvcp140.dll, ingen sti-lekkasje til C) og til slutt REGLENE i
regler/ (uten dem nekter serveren å starte). Skriver en klar
OK/FEIL-rapport — ingenting antas, alt bekreftes.

Bruk (fra prosjektroten):
    python skript/sjekk_miljo.py

Avslutter med kode 0 hvis alt er grønt, ellers 1.
"""
import importlib
import io
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROT = Path(__file__).resolve().parent.parent
_feil, _advarsel = [], []


def ok(m): print(f"  [OK]   {m}")
def feil(m): _feil.append(m); print(f"  [FEIL] {m}")
def adv(m): _advarsel.append(m); print(f"  [ADV]  {m}")


def sjekk_python():
    print("\n[1] Python")
    v = sys.version_info
    (ok if (v.major, v.minor) == (3, 11) else adv)(
        f"Python {v.major}.{v.minor}.{v.micro} "
        + ("" if (v.major, v.minor) == (3, 11) else "(pakken er bygd for 3.11)"))


def sjekk_importer():
    print("\n[2] Kritiske biblioteker")
    # (importnavn, pip-navn, kritisk?)
    pakker = [
        ("fitz", "PyMuPDF", True), ("numpy", "numpy", True),
        ("PIL", "pillow", True), ("cv2", "opencv-python-headless", True),
        ("easyocr", "easyocr", True), ("torch", "torch", True),
        ("transformers", "transformers", True),
        ("llama_cpp", "llama-cpp-python", True),
        ("pyzbar.pyzbar", "pyzbar", True), ("docx", "python-docx", True),
        ("openpyxl", "openpyxl", True), ("requests", "requests", True),
        ("bs4", "beautifulsoup4", True),
        ("bitsandbytes", "bitsandbytes", False),
        ("accelerate", "accelerate", False),
        ("rapidocr", "rapidocr", False),
        ("huggingface_hub", "huggingface-hub", False),
    ]
    for modul, pip_navn, kritisk in pakker:
        try:
            m = importlib.import_module(modul)
            v = getattr(m, "__version__", "")
            ok(f"{pip_navn} {v}".rstrip())
        except Exception as exc:
            (feil if kritisk else adv)(
                f"{pip_navn} kunne ikke importeres: {exc}")


def sjekk_gpu():
    print("\n[3] GPU / CUDA")
    try:
        import torch
        ok(f"torch {torch.__version__} (CUDA-bygg: {torch.version.cuda})")
        if torch.cuda.is_available():
            ok(f"GPU tilgjengelig: {torch.cuda.get_device_name(0)} "
               f"({torch.cuda.get_device_properties(0).total_memory//1024//1024} MB)")
        else:
            adv("Ingen GPU/CUDA tilgjengelig — systemet KJØRER, men OCR og "
                "Borealis blir tregt (CPU). Sjekk NVIDIA-driver (>= 550 for "
                "CUDA 12.4) og at kortet vises i 'nvidia-smi'.")
    except Exception as exc:
        feil(f"torch/CUDA-sjekk feilet: {exc}")


def sjekk_dll():
    print("\n[4] System-DLL-er")
    try:
        import pyzbar.pyzbar  # noqa: laster zbar-DLL implisitt
        ok("pyzbar/zbar-DLL lastet (strekkode/QR virker)")
    except Exception as exc:
        feil(f"pyzbar/zbar-DLL mangler: {exc} — strekkodelesing vil feile")


def sjekk_easyocr_modeller():
    print("\n[5] EasyOCR-modeller")
    _eo = os.environ.get("EASYOCR_MODULE_PATH")
    mappe = (Path(_eo) if _eo else Path.home() / ".EasyOCR") / "model"
    pth = list(mappe.glob("*.pth")) if mappe.is_dir() else []
    if pth:
        ok(f"{len(pth)} modeller i {mappe} "
           f"({sum(f.stat().st_size for f in pth)//1024//1024} MB)")
    else:
        feil(f"Ingen EasyOCR-modeller i {mappe} — OCR vil forsøke å laste "
             "dem fra internett og FEILE offline. Kopier fra "
             "offline_pakke/easyocr_modeller/ hit.")


def sjekk_borealis():
    print("\n[6] Borealis-modell")
    gguf_mappe = ROT / "modeller" / "borealis-gguf"
    gguf = [f for f in gguf_mappe.glob("*.gguf")
            if not f.name.lower().startswith("mmproj")] if gguf_mappe.is_dir() else []
    transformers_mappe = ROT / "modeller" / "borealis"
    if gguf:
        ok(f"GGUF-modell: {gguf[0].name} "
           f"({gguf[0].stat().st_size//1024//1024} MB) — llama.cpp-backend")
    elif (transformers_mappe / "config.json").is_file():
        ok("transformers-modell i modeller/borealis (fallback-backend)")
    else:
        feil("Ingen Borealis-modell funnet. Legg en .gguf i "
             "modeller/borealis-gguf/ ELLER transformers-modellen i "
             "modeller/borealis/. (Modeller pakkes IKKE av offline-pakken "
             "— kopieres separat.)")


def sjekk_ekte_kjoring():
    print("\n[7] Ekte minitest (deterministisk uttrekk)")
    try:
        sys.path.insert(0, str(ROT))
        from delt.tekstuttrekk import strukturert_uttrekk
        r = strukturert_uttrekk(
            "Faktura\nDato: 12.03.2024\nBeløp: kr 1 234,00\n"
            "Org. nr.: 889000007")
        antar = (r["datoer"] and r["belop"]
                 and r["identifikatorer"]["organisasjonsnummer"])
        (ok if antar else feil)(
            f"uttrekk kjørte: dato={bool(r['datoer'])}, "
            f"beløp={bool(r['belop'])}, "
            f"orgnr={r['identifikatorer']['organisasjonsnummer']}")
    except Exception as exc:
        feil(f"deterministisk uttrekk feilet: {exc}")


def sjekk_regler():
    """Regelfilene i regler/ er ikke pynt: uten prompter.md vet ikke
    modellen hvilke regler den skal følge, og serveren nekter å starte
    (med vilje — et svar uten reglene er et feil svar i stillhet). En
    ufullstendig kopi skal oppdages HER, ikke ved første spørsmål."""
    print("\n[9] Regler (regler/)")
    try:
        sys.path.insert(0, str(ROT))
        from delt import prompter
    except Exception as exc:
        feil(f"kunne ikke laste regelmodulen: {exc}")
        return
    try:
        blokker = prompter.blokknavn()
        ok(f"prompter.md lest: {len(blokker)} promptblokker, "
           f"versjon {prompter.versjon()}")
    except Exception as exc:
        feil(f"regler/prompter.md mangler eller er ødelagt: {exc} "
             f"(kopierte du HELE mappa?)")
        return
    # Blokkene serveren faktisk slår opp — mangler én, feiler det
    # midt i en forespørsel i stedet for her
    for navn in ("spor.dokumentsporsmal", "spor.uten_dokument",
                 "korriger.forste_pass", "korriger.selvkontroll",
                 "fyll_skjema.mal"):
        if navn not in blokker:
            feil(f"promptblokken «{navn}» mangler i regler/prompter.md")
    # Brukerfilene er valgfrie — mangler de, kjører systemet videre
    # uten dem, og da skal det SIES, ikke antas
    for navn in ("egne_regler.txt", "egne_etiketter.txt"):
        sti = Path(prompter.regelfil(navn))
        if not sti.exists():
            adv(f"{navn} finnes ikke — ingen egne regler er aktive")
        elif sti.parent.name != "regler":
            adv(f"{navn} ligger i {sti.parent} og ikke i regler/ — "
                f"flytt den, ellers er reglene spredt igjen")
        else:
            ok(f"regler/{navn} på plass")


def sjekk_portabilitet():
    """Bekrefter at KOPIEN kjører fra seg selv (nav-lokal), ikke lener seg på
    C:/gammel maskin. Fanger de vanligste flytte-feilene på en fersk server."""
    print("\n[8] Portabilitet (nav-lokal, ingen C-binding)")
    # a) kjører vi prosjektets EGEN .pyruntime-tolk?
    forventet = ROT / ".pyruntime" / "python.exe"
    faktisk = Path(sys.executable)
    if forventet.exists():
        rett = faktisk.resolve() == forventet.resolve()
        (ok if rett else adv)(
            f"tolk: {faktisk}"
            + ("" if rett else f" — forventet {forventet} (start via START_ALT.bat)"))
    else:
        feil(f"fant ikke prosjekt-tolken: {forventet} (kopierte du HELE mappa?)")
    # b) ingen sys.path utenfor nav (C:, %APPDATA%, gammel maskin)
    rot_l = str(ROT).lower()
    lekk = [p for p in sys.path
            if p and not p.lower().startswith(rot_l) and not p.lower().endswith(".zip")]
    (ok if not lekk else adv)(
        "sys.path er ren nav-lokal" if not lekk
        else f"sys.path peker UTENFOR nav: {lekk} — sett PYTHONNOUSERSITE=1")
    # c) msvcp140.dll lastet fra .pyruntime (buntet), ikke System32/VC++-redist
    try:
        import ctypes
        import torch  # noqa: drar inn msvcp140.dll
        from ctypes import c_void_p, c_wchar_p, c_uint32
        k = ctypes.windll.kernel32
        k.GetModuleHandleW.restype = c_void_p
        k.GetModuleHandleW.argtypes = [c_wchar_p]
        k.GetModuleFileNameW.restype = c_uint32
        k.GetModuleFileNameW.argtypes = [c_void_p, c_wchar_p, c_uint32]
        h = k.GetModuleHandleW("msvcp140.dll")
        if h:
            buf = ctypes.create_unicode_buffer(300)
            k.GetModuleFileNameW(h, buf, 300)
            fra_nav = rot_l in buf.value.lower()
            (ok if fra_nav else adv)(
                f"msvcp140.dll fra: {buf.value}"
                + ("" if fra_nav else " — IKKE fra nav; bunt DLL-ene i .pyruntime "
                   "eller installer VC++ 2015-2022 x64-redist på serveren"))
        else:
            adv("msvcp140.dll ikke lastet ennå (torch importert?)")
    except Exception as exc:
        adv(f"msvcp140-sjekk hoppet over: {exc}")


def main():
    print("=" * 60)
    print("  MILJØSJEKK — NAV lokalt dokument-API")
    print("=" * 60)
    sjekk_python()
    sjekk_importer()
    sjekk_gpu()
    sjekk_dll()
    sjekk_easyocr_modeller()
    sjekk_borealis()
    sjekk_ekte_kjoring()
    sjekk_portabilitet()
    sjekk_regler()
    print("\n" + "=" * 60)
    if _feil:
        print(f"  RESULTAT: {len(_feil)} FEIL, {len(_advarsel)} advarsler")
        for m in _feil:
            print(f"   ✗ {m}")
        print("  Systemet er IKKE klart før feilene over er løst.")
        sys.exit(1)
    print(f"  RESULTAT: ALT GRØNT ({len(_advarsel)} advarsler)")
    if _advarsel:
        for m in _advarsel:
            print(f"   ! {m}")
    print("  Systemet er klart. Start: python skript/dokument_api.py")
    sys.exit(0)


if __name__ == "__main__":
    main()
