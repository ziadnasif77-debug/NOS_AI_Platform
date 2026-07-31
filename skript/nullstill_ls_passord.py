"""
Nullstiller passordet til en Label Studio-bruker i NAV-installasjonen.

Passordet skrives av DEG, skjult (getpass) — det vises aldri på skjermen
og lagres ingen steder. Skriptet setter bare opp riktig database først.

FELLE SOM DETTE UNNGÅR: uten LABEL_STUDIO_BASE_DATA_DIR bruker
Label Studio standardkatalogen i brukerprofilen på C:, altså en HELT
ANNEN (tom) database. Kommandoen ville da meldt «User not found» — eller
i verste fall endret passordet i feil base, mens innlogging fortsatt
feilet i den ekte. Her pekes den alltid på nav\\data\\label-studio.

  python skript/nullstill_ls_passord.py                 (spør om bruker)
  python skript/nullstill_ls_passord.py <e-post>
  python skript/nullstill_ls_passord.py --vis-brukere   (bare list dem)

Stopp Label Studio først hvis du får «database is locked».
"""
import io
import os
import sqlite3
import sys

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.setdefault(
    "LABEL_STUDIO_BASE_DATA_DIR", os.path.join(ROT, "data", "label-studio"))
os.environ.setdefault("PYTHONNOUSERSITE", "1")
DB = os.path.join(DATA_DIR, "label_studio.sqlite3")


def vis_brukere() -> list:
    """Leser brukerlista direkte fra databasen (kun lesing). Rask, og
    virker selv om Label Studio ikke lar seg starte."""
    if not os.path.isfile(DB):
        print(f"Fant ingen database her: {DB}")
        print("Er Label Studio startet minst én gang fra denne mappa?")
        return []
    kobling = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rader = kobling.execute(
            "SELECT email, username, is_active, last_login "
            "FROM htx_user ORDER BY id").fetchall()
    except sqlite3.Error as exc:
        print(f"Klarte ikke å lese brukertabellen: {exc}")
        return []
    finally:
        kobling.close()

    print(f"Brukere i {DB}:")
    for e_post, brukernavn, aktiv, sist in rader:
        merke = "" if aktiv else "   (DEAKTIVERT)"
        print(f"  {e_post}   (brukernavn: {brukernavn}, "
              f"sist innlogget: {sist or 'aldri'}){merke}")
    return [r[0] for r in rader]


def main() -> int:
    if "--vis-brukere" in sys.argv:
        return 0 if vis_brukere() else 1

    e_poster = vis_brukere()
    if not e_poster:
        return 1

    argumenter = [a for a in sys.argv[1:] if not a.startswith("-")]
    if argumenter:
        bruker = argumenter[0]
    elif len(e_poster) == 1:
        bruker = e_poster[0]
        print(f"\nBruker: {bruker}")
    else:
        bruker = input("\nHvilken e-post? ").strip()

    if bruker not in e_poster:
        print(f"\n«{bruker}» finnes ikke i denne databasen — se lista over.")
        return 1

    print("Skriv det nye passordet (det vises ikke mens du skriver):\n")
    # Label Studio spør selv med getpass når --password utelates, så
    # passordet går aldri gjennom kommandolinjen (der det ville havnet i
    # skallhistorikk og prosesslista).
    sys.argv = ["label-studio", "reset_password", "--username", bruker]
    from label_studio.server import main as ls_main
    try:
        ls_main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
