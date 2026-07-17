"""
Enkel test: analyser en PDF og skriv ut feltene — uten server, uten Docker.

Bruk (fra mappen D:\\nav):
    python skript/test_pdf.py "D:/nav/data/inntak/2254711543.pdf"

Eller uten argument → bruker eksempelfilen:
    python skript/test_pdf.py

Leser PDF-ens tekstlag (PyMuPDF) og kjører det deterministiske
uttrekkslaget (mod11, anti-hallusinering). Skriver ut feltene pent.
Kun Python + PyMuPDF — svar på millisekunder.
"""
import io
import os
import sys

# UTF-8 på konsollen (Windows-terminaler krasjer ellers på æ/ø/å)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)

from delt.tekstuttrekk import utvid_entiteter


def analyser(sti: str):
    sti = sti.strip().strip('"').strip("'")
    print("=" * 60)
    print(f"  Analyserer: {sti}")
    print("=" * 60)

    if not os.path.isfile(sti):
        print(f"  FEIL: fil finnes ikke.")
        return
    if not sti.lower().endswith(".pdf"):
        print("  FEIL: kun PDF støttes.")
        return

    try:
        import fitz
    except ImportError:
        print("  FEIL: PyMuPDF mangler. Kjør:  pip install pymupdf")
        return

    doc = fitz.open(sti)
    antall_sider = doc.page_count
    total_tekst = ""
    felter = {}
    for side in doc:
        tekst = side.get_text() or ""
        total_tekst += tekst
        for k, v in utvid_entiteter(tekst, {}).items():
            felter.setdefault(k, v)
    doc.close()

    print(f"  Antall sider:      {antall_sider}")
    print(f"  Tegn i tekstlag:   {len(total_tekst.strip())}")
    print()

    if len(total_tekst.strip()) < 20:
        print("  ⚠  Dokumentet har lite/ingen tekstlag (trolig skannet bilde).")
        print("     Deterministisk uttrekk kan ikke lese bilder — trenger OCR.")
        return

    if not felter:
        print("  Ingen strukturerte felter funnet (men det finnes tekst).")
    else:
        print("  UTTRUKKEDE FELTER:")
        for k, v in felter.items():
            print(f"     {k:14} : {v}")
    print()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sti = sys.argv[1]
    else:
        sti = os.path.join(ROT, "data", "inntak", "2254711543.pdf")
        print("(ingen fil oppgitt — bruker eksempelfilen)\n")
    analyser(sti)
