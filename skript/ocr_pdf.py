"""
OCR av en skannet/bilde-PDF — leser teksten fra bildet, lokalt på GPU.

For PDF-er UTEN tekstlag (skannet, håndskrift) som test_pdf.py/spor_pdf.py
ikke kan lese. Bruker EasyOCR (støtter norsk, kjører på GPU), renderer
hver side til bilde og trekker ut teksten. Deretter kjøres det samme
deterministiske uttrekkslaget (mod11, anti-hallusinering) på OCR-teksten.

Bruk (fra D:\\nav):
    python skript/ocr_pdf.py "D:/nav/data/inntak/handskrift_norsk.pdf"

Ingen Docker. Første kjøring laster EasyOCR sine norske modeller (liten,
én gang). Kun EasyOCR + PyMuPDF (allerede installert).

MERK: OCR på ETTERLIGNET håndskrift/skannede dokumenter er aldri perfekt.
For ekte håndskrift er norhand/TrOCR i full pipeline bedre. Dette gir deg
en rask lokal test av OCR-veien.
"""
import io
import os
import sys

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)

from delt.tekstuttrekk import utvid_entiteter

_leser = None


def _hent_leser():
    """Laster EasyOCR én gang (norsk + engelsk, GPU hvis mulig)."""
    global _leser
    if _leser is None:
        import easyocr
        try:
            import torch
            gpu = torch.cuda.is_available()
        except Exception:
            gpu = False
        print(f"Laster EasyOCR (norsk) på {'GPU' if gpu else 'CPU'} — vent litt ...")
        _leser = easyocr.Reader(["no", "en"], gpu=gpu)
        print("EasyOCR klar.\n")
    return _leser


def ocr_pdf(sti: str) -> str:
    """Renderer hver side til bilde og OCR-er den. Returnerer samlet tekst."""
    import fitz
    import numpy as np

    leser = _hent_leser()
    doc = fitz.open(sti)
    all_tekst = []
    for i, side in enumerate(doc):
        # 200 dpi gir god OCR-kvalitet
        pix = side.get_pixmap(matrix=fitz.Matrix(200 / 72, 200 / 72))
        bilde = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:      # RGBA → RGB
            bilde = bilde[:, :, :3]
        resultat = leser.readtext(bilde, detail=0, paragraph=True)
        side_tekst = "\n".join(resultat)
        all_tekst.append(side_tekst)
        print(f"--- Side {i + 1} ({len(side_tekst)} tegn OCR-et) ---")
        print(side_tekst)
        print()
    doc.close()
    return "\n".join(all_tekst)


def main():
    if len(sys.argv) < 2:
        print('Bruk: python skript/ocr_pdf.py "sti/til/skannet.pdf"')
        return
    sti = sys.argv[1].strip().strip('"')
    if not os.path.isfile(sti):
        print(f"Fil finnes ikke: {sti}")
        return

    print("=" * 60)
    print(f"  OCR av: {os.path.basename(sti)}")
    print("=" * 60 + "\n")

    tekst = ocr_pdf(sti)

    if len(tekst.strip()) < 5:
        print("OCR fant ingen tekst i bildet.")
        return

    felter = utvid_entiteter(tekst, {})
    print("=" * 60)
    print("  DETERMINISTISK UTTREKK FRA OCR-TEKSTEN:")
    print("=" * 60)
    if felter:
        for k, v in felter.items():
            print(f"     {k:14} : {v}")
    else:
        print("     (ingen strukturerte felter gjenkjent i OCR-teksten)")
    print()


if __name__ == "__main__":
    main()
