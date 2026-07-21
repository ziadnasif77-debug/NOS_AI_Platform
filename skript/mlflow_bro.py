"""
Bro til MLflow som kjører i et ISOLERT venv.

mlflow kan ikke importeres i hovedmiljøet (mlflow 2.x krever pyarrow<19,
som kolliderer med datasets/label-studio). Så vi logger et treningsløp
ved å kalle det isolerte venv-ets python på _mlflow_skriv.py via
subprocess. Best-effort: mangler venv-et, er logg() en stille no-op og
treningsløkken kjører uansett.

Sett MLFLOW_VENV_PYTHON hvis venv-et ligger et annet sted.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

MLFLOW_STI = os.environ.get("MLFLOW_STI", "./data/mlflow")
_STD = (".venv-mlflow/Scripts/python.exe" if os.name == "nt"
        else ".venv-mlflow/bin/python")
MLFLOW_VENV_PYTHON = os.environ.get("MLFLOW_VENV_PYTHON", _STD)


def tilgjengelig() -> bool:
    """True hvis det isolerte MLflow-venv-et finnes."""
    return Path(MLFLOW_VENV_PYTHON).exists()


def logg(run_name: str, params: dict, metrikker: dict) -> bool:
    """Logger ett løp til MLflow via det isolerte venv-et. True hvis logget,
    False hvis venv-et mangler eller loggingen feilet (best-effort)."""
    if not tilgjengelig():
        return False
    # Absolutt sti — subprocess på Windows finner ikke en relativ exe.
    py = str(Path(MLFLOW_VENV_PYTHON).resolve())
    skriver = str(Path(__file__).resolve().parent / "_mlflow_skriv.py")
    nyttelast = json.dumps({
        "tracking_uri": Path(MLFLOW_STI).resolve().as_uri(),
        "experiment": "nav-trening",
        "run_name": run_name,
        "params": params or {},
        "metrics": {k: v for k, v in (metrikker or {}).items() if v is not None},
    })
    try:
        r = subprocess.run(
            [py, skriver],
            input=nyttelast, text=True, capture_output=True, timeout=90)
        if r.returncode != 0:
            print(f"  [mlflow] logging feilet: {r.stderr.strip()[:200]}",
                  file=sys.stderr)
            return False
        return True
    except Exception as exc:
        print(f"  [mlflow] logging hoppet over: {exc}", file=sys.stderr)
        return False
