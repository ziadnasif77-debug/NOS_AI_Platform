"""
Lager en STOR syntetisk bunke — til 500-sidersmålingen (§30).

    .pyruntime\\python.exe skript\\lag_stor_bunke.py            # 500 sider
    .pyruntime\\python.exe skript\\lag_stor_bunke.py --sider 200

Implementeringsspesifikasjonen krever at «500-siders scanned path
fullfører med full OCR coverage når dette kreves, uten stille
truncation». Det kravet kan ikke prøves uten et 500-siders skannet
dokument, og et slikt fantes ikke.

HVORFOR SIDENE GJENBRUKES
Bunken bygges av den eksisterende 10-siders SKANNEDE bunken, gjentatt.
`show_pdf_page` legger inn en REFERANSE til kildesiden, så de 500
sidene deler ti bilder: fila blir ~4 MB i stedet for ~180, og den kan
lastes opp uten å slå i taket på opplastingsgrensen.

DET MÅLINGEN DA FAKTISK MÅLER
Gjennomstrømning og dekning — altså nøyaktig det §30 spør om: kommer
alle 500 sidene gjennom, og sier systemet ærlig fra hvis de ikke gjør
det. Den måler IKKE innholdsvariasjon: side 11 er den samme som side 1,
så uttrekket blir repetitivt. Det er en egenskap ved denne målingen, og
den skal sies høyt i stedet for å bli lest som noe den ikke er.

Personvern: kilden er den syntetiske bunken (tester/korpus/README.md).
Ingen ekte dokumenter, her som ellers.
"""
import argparse
import os
import sys

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                               # noqa: BLE001
    pass

KILDE = os.path.join(ROT, "data", "korpus", "syntetisk_bunke_skann.pdf")


def lag(sider: int, ut_sti: str) -> str:
    import fitz
    if not os.path.isfile(KILDE):
        raise SystemExit(
            f"Fant ikke kilden: {KILDE}\n"
            "Den syntetiske bunken ligger ikke i git (data/ er ignorert) — "
            "kopier data/korpus/ fra servermappa.")
    kilde = fitz.open(KILDE)
    if not kilde.page_count:
        raise SystemExit("Kildebunken har ingen sider.")
    ut = fitz.open()
    for nr in range(sider):
        kildeside = kilde[nr % kilde.page_count]
        ny = ut.new_page(width=kildeside.rect.width,
                         height=kildeside.rect.height)
        # Referanse, ikke kopi: de 500 sidene deler kildens ti bilder.
        ny.show_pdf_page(ny.rect, kilde, nr % kilde.page_count)
    os.makedirs(os.path.dirname(ut_sti), exist_ok=True)
    ut.save(ut_sti, garbage=4, deflate=True)
    ut.close()
    kilde.close()
    return ut_sti


def main() -> int:
    p = argparse.ArgumentParser(description="Stor syntetisk bunke")
    p.add_argument("--sider", type=int, default=500)
    p.add_argument("--ut", default=os.path.join(
        ROT, "data", "korpus", "syntetisk_bunke_500.pdf"))
    args = p.parse_args()

    sti = lag(args.sider, args.ut)
    mb = os.path.getsize(sti) / (1024 ** 2)

    import fitz
    d = fitz.open(sti)
    har_tekstlag = any((d[i].get_text() or "").strip()
                       for i in range(min(5, d.page_count)))
    print(f"  Laget:      {os.path.relpath(sti, ROT)}")
    print(f"  Sider:      {d.page_count}")
    print(f"  Størrelse:  {mb:.1f} MB")
    print(f"  Tekstlag:   {'JA — da blir det ingen OCR-måling!' if har_tekstlag else 'nei (OCR tvinges, som det skal)'}")
    d.close()
    return 0 if not har_tekstlag else 1


if __name__ == "__main__":
    sys.exit(main())
