"""
Laster ned alle AI-modeller fra HuggingFace.
Kjores en gang ved forste oppsett.
Alle modeller lagres lokalt — ingen internettilgang etterpaa.
"""
from huggingface_hub import snapshot_download
import os

MODELLER_STI = os.environ.get("MODELLER_STI", "./modeller")

MODELLER = {
    "norhand":     "Sprakbanken/TrOCR-norhand-v3",
    "nb-bert":     "NbAiLab/nb-bert-base",
    "nb-bert-ner": "NbAiLab/nb-bert-base-ner",
    "borealis":    "NbAiLab/borealis-4b-instruct-preview",
    "qwen3-embed": "Qwen/Qwen3-Embedding-0.6B",
    "layoutlmv3":  "microsoft/layoutlmv3-base",
}

for mappe, modell_id in MODELLER.items():
    utgang = f"{MODELLER_STI}/{mappe}"
    print(f"Laster ned {modell_id} -> {utgang}")
    try:
        snapshot_download(repo_id=modell_id, local_dir=utgang)
        print(f"✓ {modell_id} lastet ned")
    except Exception as feil:
        print(f"✗ Feil ved nedlasting av {modell_id}: {feil}")

print("\nForhåndsinstallerer Marker OCR-modeller...")
try:
    import subprocess
    subprocess.run(
        ["python", "-c", "from marker.models import load_all_models; load_all_models()"],
        check=True
    )
    print("✓ Marker OCR-modeller lastet ned")
except Exception as feil:
    print(f"✗ Marker-feil: {feil}")

print("\nAlle modeller er lastet ned. Systemet er klart for offline-drift.")
