"""
Regresjonstest for D7: VALIDATION-tilstand skal alltid mappes til nlp-køen,
ikke til den ukonsumerte validation-køen.

Bakgrunn:
  NLPWorker utfører validering inline og setter done_state="ROUTING" —
  ingen worker konsumerer queue:validation. Jobs som sitter fast i VALIDATION
  (f.eks. ved krasj midt i NLP-behandling) må sendes tilbake til nlp-køen
  for å bli behandlet på nytt.
"""
import sys
import os
import importlib.util

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.config_loader import CONFIG


def _last_modul(navn, sti):
    from unittest.mock import MagicMock
    # Mock tunge avhengigheter som ikke er installert i testmiljø
    for dep in ("psycopg2", "psycopg2.extras", "redis"):
        if dep not in sys.modules:
            sys.modules[dep] = MagicMock()
    spec = importlib.util.spec_from_file_location(navn, sti)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_rebuild_redis_validation_mapping():
    """rebuild_redis.py skal mappe VALIDATION → queue:nlp (ikke queue:validation)."""
    mod = _last_modul(
        "rebuild_redis",
        os.path.join(os.path.dirname(__file__), "..", "skript", "rebuild_redis.py"),
    )

    nlp_ko = CONFIG["redis"]["kooer"]["nlp"]
    validation_ko = CONFIG["redis"]["kooer"]["validation"]

    assert mod.STATE_TIL_KO["VALIDATION"] == nlp_ko, (
        f"rebuild_redis VALIDATION mappes til '{mod.STATE_TIL_KO['VALIDATION']}', "
        f"forventet '{nlp_ko}' (nlp-køen). "
        f"Ingen worker konsumerer '{validation_ko}' — jobs vil forsvinne."
    )
    assert mod.STATE_TIL_KO["VALIDATION"] != validation_ko, (
        "rebuild_redis sender VALIDATION-jobs til den ukonsumerte validation-køen!"
    )


def test_reconciliation_validation_mapping():
    """reconciliation_worker.py skal mappe VALIDATION → nlp (konsistent med rebuild_redis)."""
    mod = _last_modul(
        "reconciliation_worker",
        os.path.join(
            os.path.dirname(__file__),
            "..", "tjenester", "workers", "reconciliation", "reconciliation_worker.py",
        ),
    )

    assert mod.STATE_TIL_KO.get("VALIDATION") == "nlp", (
        f"reconciliation_worker VALIDATION mappes til '{mod.STATE_TIL_KO.get('VALIDATION')}', "
        "forventet 'nlp'."
    )


def test_validation_mapping_consistent():
    """rebuild_redis og reconciliation_worker skal ha identisk VALIDATION-semantikk."""
    rebuild = _last_modul(
        "rebuild_redis",
        os.path.join(os.path.dirname(__file__), "..", "skript", "rebuild_redis.py"),
    )
    recon = _last_modul(
        "reconciliation_worker",
        os.path.join(
            os.path.dirname(__file__),
            "..", "tjenester", "workers", "reconciliation", "reconciliation_worker.py",
        ),
    )

    rebuild_ko = rebuild.STATE_TIL_KO.get("VALIDATION")
    recon_ko_navn = recon.STATE_TIL_KO.get("VALIDATION")
    nlp_ko = CONFIG["redis"]["kooer"]["nlp"]

    # reconciliation bruker logiske navn ("nlp"), rebuild bruker fulle kø-navn
    assert rebuild_ko == nlp_ko, (
        f"rebuild_redis VALIDATION='{rebuild_ko}', forventet '{nlp_ko}'"
    )
    assert recon_ko_navn == "nlp", (
        f"reconciliation_worker VALIDATION='{recon_ko_navn}', forventet 'nlp'"
    )
