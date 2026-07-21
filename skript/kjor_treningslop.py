"""
Kjører HELE treningsløkken som ett sporbart løp:

  1) eksporter korreksjoner fra Label Studio  ->  data/finjustering/trocr_*.json
  2) finjuster norhand (TrOCR)                 ->  KANDIDAT (ikke live)
  3) kvalitetsport: evaluer kandidat vs live (CER), promoter BARE hvis minst
     like god (valider_modell.py) — ellers står live urørt
  (deretter starter du serveren på nytt for å ta en promotert modell i bruk)

Løpet spores i MLflow (antall korreksjoner, CER live/kandidat, utfall,
varighet). MLflow kjører i et ISOLERT venv (mlflow_bro.py) fordi det
kolliderer med datasets/label-studio i hovedmiljøet. Mangler venv-et,
kjører løkken likevel — bare uten sporing. Se løpene med:

    .venv-mlflow/Scripts/mlflow ui --backend-store-uri file:///<sti>/data/mlflow

Planlegg tilbakevendende kjøring med Windows Task Scheduler.
"""
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Gjør utskrift UTF-8-trygg: æøå (og norske navn i loggen) skal ikke
# krasje når stdout er omdirigert til en fil med et ikke-UTF-8-kodesett.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mlflow_bro


def kjor() -> None:
    start = time.time()
    run_name = f"trening-{datetime.now():%Y%m%d-%H%M%S}"
    p = {"startet": datetime.now().isoformat()}
    m = {}
    try:
        # 1) Eksport fra Label Studio
        print("=== 1/3  Eksporterer korreksjoner fra Label Studio ===")
        import eksporter_fra_label_studio as eksport
        antall_eksportert = eksport.eksporter() or 0
        m["eksporterte_korreksjoner"] = antall_eksportert
        if antall_eksportert == 0:
            print("Ingen nye korreksjoner — hopper over trening.")
            p["resultat"] = "ingen_data"
            return

        # 2) Finjuster norhand (TrOCR) → KANDIDAT (ikke live)
        print("\n=== 2/3  Finjusterer norhand (TrOCR) → kandidat ===")
        import finjuster
        antall_trent = finjuster.finjuster_norhand()
        m["trente_eksempler"] = antall_trent or 0
        if not antall_trent:
            print("For få korreksjoner — ingen kandidat trent.")
            p["resultat"] = "for_faa"
            return

        # 3) Kvalitetsport: kandidat vs live på et fast valideringssett.
        # Promoter BARE hvis kandidaten er minst like god (lavere/lik CER),
        # så en dårlig batch aldri når produksjon — den stoppes i porten.
        print("\n=== 3/3  Kvalitetsport: kandidat vs live (CER) ===")
        import valider_modell as vm
        v = vm.vurder()
        p["cer_live"] = v["cer_live"]
        p["cer_kandidat"] = v["cer_kandidat"]
        p["validering_antall"] = v["antall"]
        if v["cer_live"] is not None:
            m["cer_live"] = v["cer_live"]
        if v["cer_kandidat"] is not None:
            m["cer_kandidat"] = v["cer_kandidat"]

        if v["godkjent"]:
            vm.promuster()
            p["resultat"] = "promotert"
            print(f"GODKJENT (CER {v['cer_kandidat']} <= {v['cer_live']}). "
                  "Server-omstart tar den nye modellen i bruk.")
        elif v["grunn"] == "mangler_valideringssett":
            p["resultat"] = "ingen_valideringssett"
            print("INGEN valideringssett — kandidaten er IKKE promotert. Lag "
                  f"{vm.VALIDERING_STI} for automatisk promotering, eller "
                  "promoter manuelt: python skript/valider_modell.py --promuster")
        else:
            p["resultat"] = "avvist_daarligere"
            print(f"AVVIST (CER {v['cer_kandidat']} > {v['cer_live']}). Live "
                  "urørt; kandidat i modeller/norhand-kandidat. Rull tilbake: "
                  "python skript/valider_modell.py --rull-tilbake")
    finally:
        m["varighet_sek"] = round(time.time() - start, 1)
        # Logg hele løpet til MLflow i ETT kall (via det isolerte venv-et).
        if mlflow_bro.logg(run_name, p, m):
            print(f"\nSporet i MLflow: {run_name}")
        print("Ferdig.")


if __name__ == "__main__":
    kjor()
