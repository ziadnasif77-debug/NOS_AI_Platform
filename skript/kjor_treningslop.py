"""
Kjører HELE treningsløkken som ett sporbart løp:

  1) eksporter korreksjoner fra Label Studio  ->  data/finjustering/trocr_*.json
  2) finjuster norhand (TrOCR) på korreksjonene
  (deretter starter du serveren på nytt for å ta modellen i bruk)

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

        # 2) Finjuster norhand (TrOCR)
        print("\n=== 2/2  Finjusterer norhand (TrOCR) ===")
        import finjuster
        antall_trent = finjuster.finjuster_norhand()
        _metrikk("trente_eksempler", antall_trent or 0)
        _param("resultat", "trent" if antall_trent else "for_faa")

        modell_sti = Path(finjuster.MODELLER_STI) / "norhand"
        if antall_trent and modell_sti.exists():
            _param("modell_sti", str(modell_sti.resolve()))

        _metrikk("varighet_sek", round(time.time() - start, 1))

    print("\nFerdig. Start serveren på nytt for å ta den nytrente modellen "
          "i bruk (modeller lastes ved oppstart).")


if __name__ == "__main__":
    kjor()
