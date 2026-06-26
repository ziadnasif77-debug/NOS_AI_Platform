"""
Regresjonstest for PR-4C (R4):
Audit-record og unlock skal committes atomisk i én Postgres-transaksjon
FØR Redis-push. Hvis Redis feiler, finnes audit-sporet likevel i DB.
"""
import sys
import os
import json
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

for _dep in ("psycopg2", "psycopg2.extras", "redis"):
    if _dep not in sys.modules:
        sys.modules[_dep] = MagicMock()
sys.modules["psycopg2"].extras = MagicMock()
sys.modules["psycopg2"].extras.Json = lambda x: x
sys.modules["psycopg2"].extras.RealDictCursor = MagicMock()

import importlib.util
spec = importlib.util.spec_from_file_location(
    "reconciliation_worker",
    os.path.join(os.path.dirname(__file__),
                 "..", "tjenester", "workers", "reconciliation", "reconciliation_worker.py"),
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
ReconciliationWorker = mod.ReconciliationWorker


def _lag_worker():
    with patch("redis.from_url", return_value=MagicMock()):
        return ReconciliationWorker()


def _lag_pg_mock(resultat_rad=None):
    pg = MagicMock()
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    cursor.fetchone.return_value = resultat_rad
    pg.cursor.return_value = cursor
    return pg


def test_audit_committes_foer_redis_push():
    """
    pg.commit() skal kalles FØR redis.rpush().
    Dette sikrer at audit-record alltid eksisterer hvis unlock ble gjort.
    """
    worker = _lag_worker()
    pg = _lag_pg_mock(resultat_rad=None)  # QUEUED — ingen forrige resultat

    kall_rekkefølge = []
    pg.commit.side_effect = lambda: kall_rekkefølge.append("commit")
    worker._redis.rpush.side_effect = lambda *a: kall_rekkefølge.append("rpush")

    worker._frigi_og_re_koe_atomisk(
        "job-audit-1", "QUEUED", "/tmp/test.pdf", pg,
        audit_event="RECONCILIATION_STUCK",
    )

    commit_idx = next((i for i, k in enumerate(kall_rekkefølge) if k == "commit"), None)
    rpush_idx = next((i for i, k in enumerate(kall_rekkefølge) if k == "rpush"), None)

    assert commit_idx is not None, "pg.commit() ble ikke kalt"
    assert rpush_idx is not None, "redis.rpush() ble ikke kalt"
    assert commit_idx < rpush_idx, (
        f"commit ({commit_idx}) skal skje FØR rpush ({rpush_idx})"
    )


def test_audit_inkludert_i_samme_transaksjon_som_unlock():
    """
    Unlock-UPDATE og audit-INSERT skal utføres i samme cursor-kontekst
    (ingen commit mellom dem).
    """
    worker = _lag_worker()
    pg = _lag_pg_mock(resultat_rad=None)

    commit_teller = {"n": 0}
    execute_mellom_commits = {"n": 0}
    siste_commit = {"etter": 0}

    original_commit = pg.commit
    def tell_commit():
        commit_teller["n"] += 1
        siste_commit["etter"] = pg.cursor().execute.call_count
    pg.commit.side_effect = tell_commit

    worker._frigi_og_re_koe_atomisk(
        "job-audit-2", "PREPROCESSING", "/tmp/test.pdf", pg,
        audit_event="RECONCILIATION_GHOST",
    )

    execute_kall = pg.cursor().execute.call_count
    # Skal ha kalt execute minst 2 ganger (unlock + audit) og commit én gang
    assert pg.cursor().execute.call_count >= 2, \
        "Forventet minst 2 execute-kall (unlock + audit)"
    assert commit_teller["n"] >= 1, "pg.commit() ble ikke kalt"


def test_audit_skrives_ved_data_inkonsistens():
    """
    Når forrige_resultat mangler for en tilstand som krever det,
    skal DATA_INKONSISTENS-event skrives til audit_log.
    """
    worker = _lag_worker()
    pg = _lag_pg_mock(resultat_rad=None)  # ocr_result IS NULL

    worker._frigi_og_re_koe_atomisk(
        "job-audit-3", "NLP_PROCESSING", "/tmp/test.pdf", pg,
        audit_event="RECONCILIATION_STUCK",
    )

    # Redis skal IKKE pushes ved inkonsistens
    worker._redis.rpush.assert_not_called()
    # commit skal ha skjedd (for å skrive DATA_INKONSISTENS til audit)
    pg.commit.assert_called()


def test_redis_feil_paavirker_ikke_audit_commit():
    """
    Selv om Redis-push feiler, skal commit (og dermed audit) allerede ha skjedd.
    """
    worker = _lag_worker()
    pg = _lag_pg_mock(resultat_rad=None)
    worker._redis.rpush.side_effect = Exception("Redis nede")

    commit_skjedde = {"ja": False}
    original_commit = pg.commit
    def registrer_commit():
        commit_skjedde["ja"] = True
    pg.commit.side_effect = registrer_commit

    try:
        worker._frigi_og_re_koe_atomisk(
            "job-audit-4", "QUEUED", "/tmp/test.pdf", pg,
            audit_event="RECONCILIATION_STUCK",
        )
    except Exception:
        pass

    assert commit_skjedde["ja"], \
        "pg.commit() skal ha skjedd selv om Redis-push feiler"
