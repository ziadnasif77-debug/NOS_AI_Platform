"""
Kjører HELE treningsløkken som ett sporbart løp:

  1) eksporter korreksjoner fra Label Studio  ->  data/finjustering/trocr_*.json
  2) finjuster norhand (TrOCR)                 ->  KANDIDAT (ikke live)
  3) kvalitetsport: evaluer kandidat vs live (CER) og promoter BARE hvis
     den er minst like god — ellers står live urørt (valider_modell.py)
  (deretter starter du serveren på nytt for å ta en promotert modell i bruk)

Dette er den LETTE erstatningen for en Kubeflow-pipeline: samme DAG
(eksporter -> tren) og samme sporing (MLflow — åpen kildekode, Apache 2.0,
kjører 100 % lokalt), men uten Kubernetes. Se løpene i nettleseren med:

    mlflow ui --backend-store-uri ./data/mlflow

MLflow er VALGFRITT. Er det ikke installert, kjører løkken likevel — bare
uten sporing. Planlegg tilbakevendende kjøring med Windows Task Scheduler
(f.eks. ukentlig): pek den på «python skript/kjor_treningslop.py».
"""
import os
import sys
import time
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Filbasert MLflow-lager (ingen server nødvendig). Valgfritt.
MLFLOW_STI = os.environ.get("MLFLOW_STI", "./data/mlflow")
try:
    import mlflow
    Path(MLFLOW_STI).mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(Path(MLFLOW_STI).resolve().as_uri())
    mlflow.set_experiment("nav-trening")
    HAR_MLFLOW = True
except Exception as feil:
    print(f"MLflow ikke tilgjengelig ({feil}) — kjører uten sporing.")
    HAR_MLFLOW = False


def _param(navn: str, verdi) -> None:
    if HAR_MLFLOW:
        mlflow.log_param(navn, verdi)


def _metrikk(navn: str, verdi: float) -> None:
    if HAR_MLFLOW:
        mlflow.log_metric(navn, verdi)


def kjor() -> None:
    start = time.time()

    # Be Hugging Face-treneren logge treningstap inn i DETTE MLflow-løpet.
    # Må settes FØR finjuster importeres (den leser variabelen ved import).
    if HAR_MLFLOW:
        os.environ["TRENING_RAPPORT"] = "mlflow"

    run = (mlflow.start_run(run_name=f"trening-{datetime.now():%Y%m%d-%H%M%S}")
           if HAR_MLFLOW else nullcontext())
    with run:
        _param("startet", datetime.now().isoformat())

        # 1) Eksport fra Label Studio
        print("=== 1/2  Eksporterer korreksjoner fra Label Studio ===")
        import eksporter_fra_label_studio as eksport
        antall_eksportert = eksport.eksporter() or 0
        _metrikk("eksporterte_korreksjoner", antall_eksportert)

        if antall_eksportert == 0:
            print("Ingen nye korreksjoner — hopper over trening.")
            _param("resultat", "ingen_data")
            _metrikk("varighet_sek", round(time.time() - start, 1))
            return

        # 2) Finjuster norhand (TrOCR) → KANDIDAT (ikke live)
        print("\n=== 2/3  Finjusterer norhand (TrOCR) → kandidat ===")
        import finjuster
        antall_trent = finjuster.finjuster_norhand()
        _metrikk("trente_eksempler", antall_trent or 0)
        if not antall_trent:
            _param("resultat", "for_faa")
            _metrikk("varighet_sek", round(time.time() - start, 1))
            print("For få korreksjoner — ingen kandidat trent.")
            return

        # 3) Kvalitetsport: kandidat vs live på et fast valideringssett.
        # Promoter BARE hvis kandidaten er minst like god (lavere/lik CER).
        # Slik når en dårlig batch aldri produksjon — den stoppes i porten.
        print("\n=== 3/3  Kvalitetsport: kandidat vs live (CER) ===")
        import valider_modell as vm
        v = vm.vurder()
        _param("cer_live", v["cer_live"])
        _param("cer_kandidat", v["cer_kandidat"])
        _param("validering_antall", v["antall"])
        if v["cer_live"] is not None:
            _metrikk("cer_live", v["cer_live"])
        if v["cer_kandidat"] is not None:
            _metrikk("cer_kandidat", v["cer_kandidat"])

        if v["godkjent"]:
            vm.promuster()
            _param("resultat", "promotert")
            print(f"GODKJENT (CER {v['cer_kandidat']} ≤ {v['cer_live']}). "
                  "Server-omstart tar den nye modellen i bruk.")
        elif v["grunn"] == "mangler_valideringssett":
            _param("resultat", "ingen_valideringssett")
            print("INGEN valideringssett — kandidaten er IKKE promotert "
                  "(porten kan ikke bekrefte at den er trygg). Lag "
                  f"{vm.VALIDERING_STI} for å aktivere automatisk promotering, "
                  "eller promoter manuelt: python skript/valider_modell.py --promuster")
        else:
            _param("resultat", "avvist_daarligere")
            print(f"AVVIST (CER {v['cer_kandidat']} > {v['cer_live']}). "
                  "Live står urørt; kandidaten ligger i modeller/norhand-kandidat "
                  "for inspeksjon. Rull tilbake ved behov: "
                  "python skript/valider_modell.py --rull-tilbake")

        _metrikk("varighet_sek", round(time.time() - start, 1))

    print("\nFerdig.")


if __name__ == "__main__":
    kjor()
