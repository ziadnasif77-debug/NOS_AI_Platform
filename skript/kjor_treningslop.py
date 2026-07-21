"""
Kjører HELE treningsløkken som ett løp:

  1) eksporter korreksjoner fra Label Studio  ->  data/finjustering/trocr_*.json
  2) finjuster norhand (TrOCR)                 ->  KANDIDAT (ikke live)
  3) kvalitetsport: evaluer kandidat vs live (CER), promoter BARE hvis minst
     like god (valider_modell.py) — ellers står live urørt
  (deretter starter du serveren på nytt for å ta en promotert modell i bruk)

Skriver et sammendrag av løpet til stdout / data/logger. Planlegg
tilbakevendende kjøring med Windows Task Scheduler.
"""
import sys
import time
from datetime import datetime
from pathlib import Path

# Gjør utskrift UTF-8-trygg: æøå (og norske navn i loggen) skal ikke krasje
# når stdout er omdirigert til en fil med et ikke-UTF-8-kodesett.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))


def kjor() -> None:
    start = time.time()
    resultat = "ukjent"
    try:
        # 1) Eksport fra Label Studio
        print("=== 1/3  Eksporterer korreksjoner fra Label Studio ===")
        import eksporter_fra_label_studio as eksport
        antall_eksportert = eksport.eksporter() or 0
        if antall_eksportert == 0:
            print("Ingen nye korreksjoner — hopper over trening.")
            resultat = "ingen_data"
            return

        # 2) Finjuster norhand (TrOCR) → KANDIDAT (ikke live)
        print("\n=== 2/3  Finjusterer norhand (TrOCR) → kandidat ===")
        import finjuster
        antall_trent = finjuster.finjuster_norhand()
        if not antall_trent:
            print("For få korreksjoner — ingen kandidat trent.")
            resultat = "for_faa"
            return

        # 3) Kvalitetsport: kandidat vs live på et fast valideringssett.
        # Promoter BARE hvis kandidaten er minst like god (lavere/lik CER),
        # så en dårlig batch aldri når produksjon — den stoppes i porten.
        print("\n=== 3/3  Kvalitetsport: kandidat vs live (CER) ===")
        import valider_modell as vm
        v = vm.vurder()
        if v["godkjent"]:
            vm.promuster()
            resultat = "promotert"
            print(f"GODKJENT (CER {v['cer_kandidat']} <= {v['cer_live']}). "
                  "Server-omstart tar den nye modellen i bruk.")
        elif v["grunn"] == "mangler_valideringssett":
            resultat = "ingen_valideringssett"
            print("INGEN valideringssett — kandidaten er IKKE promotert. Lag "
                  f"{vm.VALIDERING_STI} for automatisk promotering, eller "
                  "promoter manuelt: python skript/valider_modell.py --promuster")
        else:
            resultat = "avvist_daarligere"
            print(f"AVVIST (CER {v['cer_kandidat']} > {v['cer_live']}). Live "
                  "urørt; kandidat i modeller/norhand-kandidat. Rull tilbake: "
                  "python skript/valider_modell.py --rull-tilbake")
    finally:
        varighet = round(time.time() - start, 1)
        print(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] resultat={resultat} "
              f"varighet={varighet}s")
        print("Ferdig.")


if __name__ == "__main__":
    kjor()
