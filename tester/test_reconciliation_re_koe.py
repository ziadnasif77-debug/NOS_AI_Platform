"""
Regresjonstester for PR-4A (R2):
ReconciliationWorker skal gjenopprette forrige_resultat fra Postgres
når den re-kø-er stuck/ghost jobs i midten av pipeline.
"""
import sys
import os
import json
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock tunge avhengigheter
for _dep in ("psycopg2", "psycopg2.extras", "redis"):
    if _dep not in sys.modules:
        sys.modules[_dep] = MagicMock()
sys.modules["psycopg2"].extras = MagicMock()

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
    """Lager en pg-mock der results-tabell returnerer gitt rad."""
    pg = MagicMock()
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    cursor.fetchone.return_value = resultat_rad
    pg.cursor.return_value = cursor
    return pg


# ------------------------------------------------------------------ #
#  _hent_forrige_resultat                                              #
# ------------------------------------------------------------------ #

def test_henter_ocr_result_for_nlp_processing():
    """NLP_PROCESSING skal hente ocr_result fra results-tabellen."""
    worker = _lag_worker()
    ocr_data = {"text": "Testdokument", "confidence": 0.9}
    pg = _lag_pg_mock(resultat_rad=(ocr_data,))

    resultat = worker._hent_forrige_resultat("job-1", "NLP_PROCESSING", pg)

    assert resultat == ocr_data
    pg.cursor().execute.assert_called_once()
    kall_sql = pg.cursor().execute.call_args[0][0]
    assert "ocr_result" in kall_sql


def test_henter_nlp_result_for_routing():
    """ROUTING skal hente nlp_result fra results-tabellen."""
    worker = _lag_worker()
    nlp_data = {"nlp_confidence": 0.88, "entities": {}}
    pg = _lag_pg_mock(resultat_rad=(nlp_data,))

    resultat = worker._hent_forrige_resultat("job-2", "ROUTING", pg)

    assert resultat == nlp_data
    kall_sql = pg.cursor().execute.call_args[0][0]
    assert "nlp_result" in kall_sql


def test_returnerer_none_for_tilstander_uten_forrige_resultat():
    """QUEUED og PREPROCESSING trenger ikke forrige_resultat."""
    worker = _lag_worker()
    pg = _lag_pg_mock()

    assert worker._hent_forrige_resultat("job-3", "QUEUED", pg) is None
    assert worker._hent_forrige_resultat("job-3", "PREPROCESSING", pg) is None


def test_returnerer_none_naar_resultat_mangler_i_db():
    """Hvis results-tabellen ikke har raden, returneres None."""
    worker = _lag_worker()
    pg = _lag_pg_mock(resultat_rad=None)

    resultat = worker._hent_forrige_resultat("job-4", "NLP_PROCESSING", pg)

    assert resultat is None


# ------------------------------------------------------------------ #
#  _re_koe — med og uten forrige_resultat                             #
# ------------------------------------------------------------------ #

def test_re_koe_inkluderer_forrige_resultat():
    """_re_koe skal legge til forrige_resultat i payload når det finnes."""
    worker = _lag_worker()
    ocr_data = {"text": "hei", "confidence": 0.9, "document_type": "TRYKT"}
    pg = _lag_pg_mock(resultat_rad=(ocr_data,))

    worker._re_koe("job-5", "/tmp/test.pdf", "NLP_PROCESSING", "queue:nlp", pg)

    kall = worker._redis.rpush.call_args
    ko = kall[0][0]
    payload = json.loads(kall[0][1])

    assert ko == "queue:nlp"
    assert payload["job_id"] == "job-5"
    assert payload["forrige_resultat"] == ocr_data


def test_re_koe_uten_forrige_resultat_for_preprocessing():
    """PREPROCESSING trenger ikke forrige_resultat — payload er minimal."""
    worker = _lag_worker()
    pg = _lag_pg_mock()

    worker._re_koe("job-6", "/tmp/test.pdf", "PREPROCESSING", "queue:preprocess", pg)

    payload = json.loads(worker._redis.rpush.call_args[0][1])
    assert payload["job_id"] == "job-6"
    assert "forrige_resultat" not in payload


def test_re_koe_merker_som_feilet_naar_resultat_mangler():
    """
    Hvis NLP_PROCESSING mangler ocr_result, er jobben uopprettelig.
    _re_koe skal IKKE pushe til Redis, men merke som FAILED.
    """
    worker = _lag_worker()
    pg = _lag_pg_mock(resultat_rad=None)  # ingen ocr_result

    with patch.object(worker, "_merk_som_feilet") as mock_feilet:
        worker._re_koe("job-7", "/tmp/test.pdf", "NLP_PROCESSING", "queue:nlp", pg)

    # Skal ikke pushe til Redis
    worker._redis.rpush.assert_not_called()
    # Skal kalle _merk_som_feilet
    mock_feilet.assert_called_once_with("job-7", "NLP_PROCESSING", pg)


def test_re_koe_merker_som_feilet_naar_routing_mangler_nlp():
    """ROUTING uten nlp_result er uopprettelig — skal merkes som FAILED."""
    worker = _lag_worker()
    pg = _lag_pg_mock(resultat_rad=None)

    with patch.object(worker, "_merk_som_feilet") as mock_feilet:
        worker._re_koe("job-8", "/tmp/test.pdf", "ROUTING", "queue:routing", pg)

    worker._redis.rpush.assert_not_called()
    mock_feilet.assert_called_once()
