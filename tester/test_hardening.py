"""
H2: Postgres-URL kan overstyres med POSTGRES_URL env-variabel
H3: NameError i exception handler ved Postgres-nedetid er fikset
H4: cv2 mangler → logger WARNING, ikke stille fallback
M3: _send_til_milvus blokkerer ikke RoutingWorker (daemon thread)
L1: queue:validation ikke lenger i _legg_i_neste_ko
L2: Dead config-seksjoner (lag-flagg, old ports) fjernet
"""
import sys
import os
import logging
import threading
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _les(sti: str) -> str:
    return open(os.path.join(ROOT, sti)).read()


# ------------------------------------------------------------------ #
#  H2 — Postgres-URL fra env var                                      #
# ------------------------------------------------------------------ #

def test_postgres_url_overstyres_av_env():
    """POSTGRES_URL i miljøet skal overstyre config.yaml."""
    with patch.dict(os.environ, {"POSTGRES_URL": "postgresql://prod:secret@db:5432/nav"}):
        import importlib
        import config.config_loader as cl
        importlib.reload(cl)
        assert cl.CONFIG["postgres"]["url"] == "postgresql://prod:secret@db:5432/nav"
    importlib.reload(cl)  # tilbakestill


def test_advarsel_naar_standard_passord_brukes(caplog):
    """Manglende POSTGRES_URL med standard-passord skal gi WARNING."""
    env = {k: v for k, v in os.environ.items() if k != "POSTGRES_URL"}
    with patch.dict(os.environ, env, clear=True):
        import importlib
        import config.config_loader as cl
        with caplog.at_level(logging.WARNING):
            importlib.reload(cl)
        assert any("POSTGRES_URL" in r.message for r in caplog.records)
    importlib.reload(cl)


def test_config_loader_stoetter_redis_url_env():
    """REDIS_URL i miljøet skal overstyre config.yaml."""
    with patch.dict(os.environ, {"REDIS_URL": "redis://prod-redis:6379/1"}):
        import importlib
        import config.config_loader as cl
        importlib.reload(cl)
        assert cl.CONFIG["redis"]["url"] == "redis://prod-redis:6379/1"
    importlib.reload(cl)


# ------------------------------------------------------------------ #
#  H3 — NameError i exception handler                                 #
# ------------------------------------------------------------------ #

def test_ingen_nameerror_naar_postgres_feiler_i_handler():
    """Hvis psycopg2.connect() feiler i feilhåndtereren, skal det logges — ikke krasje."""
    for _dep in ("psycopg2", "psycopg2.extras", "redis"):
        if _dep not in sys.modules:
            sys.modules[_dep] = MagicMock()
    sys.modules["psycopg2"].extras = MagicMock()
    sys.modules["psycopg2"].extras.Json = lambda x: x

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "base_worker_h3",
        os.path.join(ROOT, "tjenester", "workers", "base_worker.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    with patch("redis.from_url", return_value=MagicMock()):
        spec.loader.exec_module(mod)

    class TestWorker(mod.BaseWorker):
        def process(self, job, pg_conn):
            raise RuntimeError("simulert prosesseringsfeil")

    with patch("redis.from_url", return_value=MagicMock()):
        worker = TestWorker.__new__(TestWorker)
        worker.worker_id = "test-h3"
        worker.queue_name = "q"
        worker.dlq_name = "dlq"
        worker.running_state = "PREPROCESSING"
        worker.done_state = "OCR_PROCESSING"
        worker._redis = MagicMock()
        worker._pg_url = "postgresql://test"

    pg_mock = MagicMock()
    pg_mock.__enter__ = MagicMock(return_value=pg_mock)
    pg_mock.__exit__ = MagicMock(return_value=False)
    pg_mock.autocommit = False

    cursor_mock = MagicMock()
    cursor_mock.__enter__ = MagicMock(return_value=cursor_mock)
    cursor_mock.__exit__ = MagicMock(return_value=False)
    cursor_mock.fetchone.return_value = ("QUEUED",)
    cursor_mock.rowcount = 1
    pg_mock.cursor.return_value = cursor_mock

    # psycopg2.connect feiler i feilhåndtereren
    with patch("psycopg2.connect", side_effect=[pg_mock, Exception("Postgres nede")]):
        try:
            worker._behandle({"job_id": "test-job-h3", "fil_sti": "/tmp/x"})
        except Exception as exc:
            assert False, f"_behandle skal ikke kaste unntak ved Postgres-nedetid: {exc}"


def test_h3_kode_er_fikset():
    """Exception handler skal ha try/except rundt psycopg2.connect()."""
    src = _les("tjenester/workers/base_worker.py")
    # Finn _behandle-metoden
    behandle_start = src.find("def _behandle(")
    behandle_blokk = src[behandle_start:]
    assert "tilkobling_exc" in behandle_blokk, \
        "psycopg2.connect() i feilhåndterer skal fanges med tilkobling_exc"
    assert "gjenopprettet av reconciliation" in behandle_blokk, \
        "Feilmeldingen skal forklare at reconciliation tar over"


# ------------------------------------------------------------------ #
#  H4 — cv2-fallback gir synlig advarsel                             #
# ------------------------------------------------------------------ #

def test_cv2_mangler_logger_warning(caplog):
    """Manglende cv2 skal gi logger.warning, ikke stille fallback."""
    src = _les("tjenester/workers/lag0_preprocessing/lag0.py")
    assert "logger.warning" in src[src.find("except ImportError"):]
    assert "cv2" in src[src.find("except ImportError"):src.find("return 0.8, TRYKT") + 50]


def test_cv2_fallback_kode_inneholder_advarsel():
    """logger.warning-kall skal komme før return i ImportError-handler."""
    src = _les("tjenester/workers/lag0_preprocessing/lag0.py")
    import_err_start = src.find("except ImportError:")
    return_pos = src.find("return 0.8, TRYKT", import_err_start)
    warning_pos = src.find("logger.warning", import_err_start)
    assert warning_pos < return_pos, \
        "logger.warning skal logges FØR fallback-return ved manglende cv2"


# ------------------------------------------------------------------ #
#  M3 — Milvus-indeksering blokkerer ikke worker                      #
# ------------------------------------------------------------------ #

def test_send_til_milvus_starter_daemon_thread():
    """_send_til_milvus skal starte en daemon-tråd, ikke blokkere."""
    src = _les("tjenester/workers/lag3_routing/lag3.py")
    assert "threading.Thread" in src, \
        "_send_til_milvus skal bruke threading.Thread"
    assert "daemon=True" in src, \
        "Milvus-tråden skal være daemon slik at den ikke hindrer prosessen i å avslutte"
    assert "_send_til_milvus_sync" in src, \
        "Synkron logikk skal være i _send_til_milvus_sync"


def test_send_til_milvus_blokker_ikke(monkeypatch):
    """_send_til_milvus() skal returnere nesten umiddelbart."""
    import time
    import importlib.util

    for _dep in ("psycopg2", "psycopg2.extras", "redis"):
        if _dep not in sys.modules:
            sys.modules[_dep] = MagicMock()
    sys.modules["psycopg2"].extras = MagicMock()
    sys.modules["psycopg2"].extras.Json = lambda x: x

    spec = importlib.util.spec_from_file_location(
        "lag3_routing_m3",
        os.path.join(ROOT, "tjenester", "workers", "lag3_routing", "lag3.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    with patch("redis.from_url", return_value=MagicMock()):
        spec.loader.exec_module(mod)

    worker = mod.RoutingWorker.__new__(mod.RoutingWorker)
    worker.worker_id = "test-m3"
    worker._redis = MagicMock()

    # Simuler treg Milvus (1 sekund)
    def treg_sync(*args, **kwargs):
        time.sleep(1.0)

    monkeypatch.setattr(worker, "_send_til_milvus_sync", treg_sync)

    nlp_mock = MagicMock()
    nlp_mock.summary = "test"
    nlp_mock.entities = {}
    nlp_mock.document_class = "skjema"

    start = time.monotonic()
    worker._send_til_milvus("job-m3", nlp_mock)
    elapsed = time.monotonic() - start

    assert elapsed < 0.1, \
        f"_send_til_milvus() blokkerte i {elapsed:.2f}s — skal returnere < 0.1s"


# ------------------------------------------------------------------ #
#  L1 — queue:validation fjernet fra _legg_i_neste_ko                #
# ------------------------------------------------------------------ #

def test_validation_ko_ikke_i_legg_i_neste_ko():
    """VALIDATION skal ikke lenger ha en oppføring i _legg_i_neste_ko."""
    src = _les("tjenester/workers/base_worker.py")
    neste_ko_start = src.find("def _legg_i_neste_ko")
    neste_ko_blokk = src[neste_ko_start:src.find("\n    def ", neste_ko_start + 1)]
    assert '"VALIDATION"' not in neste_ko_blokk, \
        "VALIDATION-oppføring i _legg_i_neste_ko skal fjernes — ingen consumer"


# ------------------------------------------------------------------ #
#  L2 — Dead config-seksjoner fjernet                                 #
# ------------------------------------------------------------------ #

def test_dead_lag_flagg_fjernet_fra_config():
    """Ubrukte lag-flagg (lag0_kvalitet etc.) skal ikke finnes i config."""
    src = _les("config/config.yaml")
    assert "lag0_kvalitet" not in src
    assert "lag1_klassifisering" not in src
    assert "lag2_ocr" not in src
    assert "lag3_nlp" not in src
    assert "lag4_validering" not in src


def test_dead_porter_fjernet_fra_config():
    """Ubrukte porter (lag0–lag5, ruter) skal ikke finnes i config."""
    src = _les("config/config.yaml")
    for port_navn in ["lag0:", "lag1:", "lag2:", "lag3:", "lag4:", "lag5:", "ruter:"]:
        assert port_navn not in src, \
            f"Død port-konfig '{port_navn}' skal fjernes fra config.yaml"
