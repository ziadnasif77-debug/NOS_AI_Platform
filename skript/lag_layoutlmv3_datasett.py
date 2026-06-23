"""
Lag LayoutLMv3-datasett fra PDF-filer ved hjelp av PaddleOCR.
Genererer JSON-filer klar for import i Label Studio.

Bruk: python skript/lag_layoutlmv3_datasett.py
Eller: make lag-datasett
"""
import os
import json
from pathlib import Path

INNTAK_STI = os.environ.get("INNTAK_STI", "./data/inntak")
UTGANG_STI = os.environ.get("PADDLEOCR_JSON_STI", "./data/paddleocr_json")


def konverter_pdf_til_png(pdf_sti: str, utgang_sti: str) -> str:
    import fitz
    dok = fitz.open(pdf_sti)
    side = dok[0]
    pix = side.get_pixmap(matrix=fitz.Matrix(2, 2))
    pix.save(utgang_sti)
    dok.close()
    return utgang_sti


def lag_label_studio_json(bilde_sti: str, fil_id: str) -> dict:
    """Kjør PaddleOCR og lag Label Studio-kompatibel JSON."""
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    resultat = ocr.ocr(bilde_sti, cls=True)

    annotations = []
    if resultat and resultat[0]:
        for linje in resultat[0]:
            boks_raa, (tekst, konf) = linje
            x_koord = [p[0] for p in boks_raa]
            y_koord = [p[1] for p in boks_raa]
            annotations.append({
                "text": tekst,
                "x": min(x_koord),
                "y": min(y_koord),
                "width": max(x_koord) - min(x_koord),
                "height": max(y_koord) - min(y_koord),
                "confidence": konf,
            })

    return {
        "data": {
            "bilde": bilde_sti,
            "fil_id": fil_id,
        },
        "predictions": [{
            "model_version": "paddleocr-3.0",
            "result": [
                {
                    "id": f"token_{i}",
                    "type": "rectanglelabels",
                    "value": {
                        "x": ann["x"],
                        "y": ann["y"],
                        "width": ann["width"],
                        "height": ann["height"],
                        "text": [ann["text"]],
                        "labels": [],
                    },
                    "score": ann["confidence"],
                }
                for i, ann in enumerate(annotations)
            ]
        }]
    }


def kjor():
    Path(UTGANG_STI).mkdir(parents=True, exist_ok=True)
    pdf_filer = list(Path(INNTAK_STI).glob("*.pdf"))
    print(f"Fant {len(pdf_filer)} PDF-filer i {INNTAK_STI}")

    for pdf_sti in pdf_filer:
        fil_id = pdf_sti.stem
        bilde_sti = f"/tmp/{fil_id}_ls.png"
        utgang_json = f"{UTGANG_STI}/{fil_id}.json"

        print(f"Behandler: {pdf_sti.name}")
        konverter_pdf_til_png(str(pdf_sti), bilde_sti)
        data = lag_label_studio_json(bilde_sti, fil_id)

        with open(utgang_json, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nJSON-filer lagret i {UTGANG_STI}")
    print("Importer disse i Label Studio for merking av NAVN, FODSELSNUMMER, DATO, ADRESSE, SIGNATUR")


if __name__ == "__main__":
    kjor()
