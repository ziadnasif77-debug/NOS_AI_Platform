"""
Laster ned AI-modellene som den kjørende serveren FAKTISK bruker.
Kjøres én gang ved første oppsett. Alt lagres lokalt — ingen
internettilgang etterpå.

Bare to modeller brukes i leseløypa (dokument_api.py + delt/):
  - norhand  : håndskrift-OCR (TrOCR)
  - borealis : norsk språkmodell (svar/utfylling)

Trykt tekst leses av EasyOCR/RapidOCR, som laster egne vekter ved første
kjøring. Tidligere lastet denne fila også ned nb-bert, nb-bert-ner,
qwen3-embed, layoutlmv3 og Marker — modeller for funksjoner som er
fjernet (klassifisering/NER/vektorsøk/layout). De er tatt bort her.
"""
from huggingface_hub import snapshot_download
import os

MODELLER_STI = os.environ.get("MODELLER_STI", "./modeller")

MODELLER = {
    "norhand":  "Sprakbanken/TrOCR-norhand-v3",
    "borealis": "NbAiLab/borealis-4b-instruct-preview",
}

for mappe, modell_id in MODELLER.items():
    utgang = f"{MODELLER_STI}/{mappe}"
    print(f"Laster ned {modell_id} -> {utgang}")
    try:
        snapshot_download(repo_id=modell_id, local_dir=utgang)
        print(f"OK  {modell_id} lastet ned")
    except Exception as feil:
        print(f"FEIL ved nedlasting av {modell_id}: {feil}")

print("\nFerdig. EasyOCR/RapidOCR henter sine egne vekter ved første OCR.")
print("Borealis kan også kjøres som GGUF — se docs/offline_installasjon.md.")
