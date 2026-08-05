"""
Lager en PDF som ETTERLIGNER norsk håndskrift — som et bilde uten
tekstlag, slik at systemet må bruke EKTE OCR (TrOCR/norhand) for å lese
den. Nyttig for å teste håndskrift-OCR-veien.

Bruk:
    python skript/lag_handskrift_pdf.py

Lager: data/inntak/handskrift_norsk.pdf
"""
import io
import os
import sys

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Norsk tekst med håndskrift-typiske linjer (søknad/brev)
LINJER = [
    "Søknad om dagpenger",
    "",
    "Navn: Ola Nordmann",
    "Fødselsnummer: 12345678910",
    "Adresse: Storgata 12, 0181 Oslo",
    "Dato: 12. mars 2024",
    "Telefon: 45 12 00 33",
    "",
    "Jeg søker herved om dagpenger etter",
    "at jeg mistet jobben min i februar.",
    "Beløp jeg søker om: kr 15 000 per måned.",
    "",
    "Med vennlig hilsen",
    "Ola Nordmann",
]

# Håndskrift-lignende fonter (fallback-rekkefølge)
FONT_KANDIDATER = [
    r"C:\Windows\Fonts\segoesc.ttf",   # Segoe Script — mest håndskrift-aktig
    r"C:\Windows\Fonts\Inkfree.ttf",
    r"C:\Windows\Fonts\segoepr.ttf",
    r"C:\Windows\Fonts\comic.ttf",
]


def main():
    from PIL import Image, ImageDraw, ImageFont

    font_sti = next((f for f in FONT_KANDIDATER if os.path.isfile(f)), None)
    if not font_sti:
        print("Fant ingen håndskrift-font — bruker standard.")
    print(f"Bruker font: {font_sti}")

    # A4 @ 150 dpi
    B, H = 1240, 1754
    bilde = Image.new("RGB", (B, H), "white")
    tegn = ImageDraw.Draw(bilde)

    y = 120
    import random
    random.seed(7)
    for linje in LINJER:
        storrelse = 54 if linje == LINJER[0] else 40
        font = ImageFont.truetype(font_sti, storrelse) if font_sti else ImageFont.load_default()
        # litt tilfeldig helning/forskyvning per linje → mer «håndskrevet»
        x = 130 + random.randint(-8, 8)
        gra = random.randint(15, 55)   # ikke helt svart — som penn
        tegn.text((x, y), linje, fill=(gra, gra, gra + 20), font=font)
        y += 80 if linje else 45

    # Lagre som PDF UTEN tekstlag (rent bilde) → tvinger OCR
    ut = os.path.join(ROT, "data", "inntak", "handskrift_norsk.pdf")
    bilde.save(ut, "PDF", resolution=150.0)
    print(f"Laget: {ut}")

    # Bekreft at det IKKE finnes tekstlag
    try:
        import fitz
        d = fitz.open(ut)
        print(f"Tegn i tekstlag: {len(d[0].get_text().strip())} (0 = ekte bilde, må OCR-es)")
        d.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
