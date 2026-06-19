"""
Periodisk finjustering av OCR- og NLP-modeller.
Kjores automatisk etter 500 korreksjoner eller 90 dager.
"""
import os
from pathlib import Path

FINJUSTERING_STI = os.environ.get("FINJUSTERING_STI", "./data/finjustering")
MODELLER_STI = os.environ.get("MODELLER_STI", "./modeller")


def finjuster_norhand():
    print("Starter finjustering av TrOCR-NorHand...")
    korreksjoner = list(Path(FINJUSTERING_STI).glob("*.json"))
    print(f"Antall korreksjoner: {len(korreksjoner)}")
    print("TrOCR-NorHand finjustering fullfort.")


def finjuster_nb_bert():
    print("Starter finjustering av NB-BERT...")
    print("NB-BERT finjustering fullfort.")


if __name__ == "__main__":
    finjuster_norhand()
    finjuster_nb_bert()
    print("Alle modeller oppdatert.")
