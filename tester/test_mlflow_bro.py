"""
Tester for MLflow-broen (mlflow_bro.py): at den degraderer TRYGT når det
isolerte MLflow-venv-et mangler — treningsløkken skal kjøre videre uten
sporing, aldri krasje.
"""
import importlib
import sys

sys.path.insert(0, "skript")

import pytest


def test_no_op_uten_venv(monkeypatch, tmp_path):
    """Mangler venv-et er logg() en stille no-op (returnerer False)."""
    monkeypatch.setenv("MLFLOW_VENV_PYTHON", str(tmp_path / "ingen-python.exe"))
    import mlflow_bro
    importlib.reload(mlflow_bro)
    assert mlflow_bro.tilgjengelig() is False
    assert mlflow_bro.logg("r", {"a": 1}, {"b": 2.0}) is False
