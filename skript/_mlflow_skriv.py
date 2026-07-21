"""
Skriver ETT MLflow-løp fra JSON på stdin. Kjøres i det ISOLERTE
MLflow-venv-et (som har mlflow; hovedmiljøet har det ikke, pga.
pyarrow-konflikt med datasets/label-studio). Kalles av mlflow_bro.py.

Stdin-JSON: {tracking_uri, experiment, run_name, params:{}, metrics:{}}
"""
import json
import sys


def main() -> int:
    d = json.load(sys.stdin)
    import mlflow
    mlflow.set_tracking_uri(d["tracking_uri"])
    mlflow.set_experiment(d.get("experiment", "nav-trening"))
    with mlflow.start_run(run_name=d.get("run_name")):
        for navn, verdi in (d.get("params") or {}).items():
            if verdi is not None:
                mlflow.log_param(navn, verdi)
        for navn, verdi in (d.get("metrics") or {}).items():
            try:
                mlflow.log_metric(navn, float(verdi))
            except (TypeError, ValueError):
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
