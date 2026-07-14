"""
Integrasjonstester mot ekte Postgres + Redis (ingen mocks på lagringslaget).

Krever kjørende tjenester og kjøres eksplisitt:

    POSTGRES_URL=postgresql://nav:nav@localhost:5432/nav_archive \
    REDIS_URL=redis://localhost:6379/0 \
    INTEGRASJONSTEST=1 python -m pytest tester/test_integrasjon_lokal.py -v

Dekker: API-auth, opplasting, idempotens, tilstandsmaskin, låsing,
preprocessing-worker ende-til-ende, routing-worker (APPROVED/REVIEW),
retry/DLQ, reconciliation (stuck/ghost/tapt), kfp_steg (kubeflow-modus)
og rebuild_redis. OCR-/NLP-modellinferens og Milvus krever GPU/modeller
og dekkes ikke her — se README «Testing».
"""
import io
import json
import os
import sys
import time
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("INTEGRASJONSTEST") != "1",
    reason="Krever kjørende Postgres/Redis — sett INTEGRASJONSTEST=1",
)

sys.path.insert(0, ".")
sys.path.insert(0, "tjenester/api")

PG_URL = os.environ.get("POSTGRES_URL", "postgresql://nav:nav@localhost:5432/nav_archive")

# Sikkerhetsvakt: testene TRUNCATE-er tabeller (inkl. audit_log).
# Nekt å kjøre mot noe som ikke utvetydig er en lokal testdatabase.
if not any(vert in PG_URL for vert in ("localhost", "127.0.0.1")):
    raise RuntimeError(
        "INTEGRASJONSTEST nektes: POSTGRES_URL peker ikke på localhost — "
        "disse testene sletter data og skal aldri kjøres mot delte miljøer."
    )

# Minimal, gyldig PDF (én tom side)
MINI_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n"
    b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n149\n%%EOF\n"
)

GYLDIG_NLP_RESULTAT = {
    "schema_version": 1,
    "job_id": "",
    "entities": {"navn": "Ola Nordmann", "dato": "2020-01-01",
                 "ytelse": "dagpenger", "fylke": "Oslo"},
    "document_class": "vedtak",
    "ytelse": "dagpenger",
    "utfall": "innvilget",
    "summary": "Vedtak om dagpenger for Ola Nordmann.",
    "nlp_confidence": 0.95,
    "nlp_model_used": "nb-bert",
    "validation": {"gyldig": True, "feil": []},
    "anomaly": {"har_anomali": False, "anomali_score": 0.1, "detaljer": []},
    "ocr_confidence": 0.97,
}


# ------------------------------------------------------------------ #
#  Fixtures                                                            #
# ------------------------------------------------------------------ #

@pytest.fixture()
def pg():
    import psycopg2
    conn = psycopg2.connect(PG_URL)
    yield conn
    conn.close()


@pytest.fixture()
def rc():
    import redis
    from config.config_loader import CONFIG
    klient = redis.from_url(CONFIG["redis"]["url"])
    yield klient
    klient.close()


@pytest.fixture(autouse=True)
def rent_miljo(pg, rc):
    """Tøm tabeller og køer før hver test (kun i test-databasen)."""
    with pg.cursor() as cur:
        cur.execute("TRUNCATE dead_letter_queue, results, audit_log, jobs CASCADE")
    pg.commit()
    rc.flushdb()
    yield


@pytest.fixture()
def api_klient():
    os.environ["API_NOKKEL"] = "test-nokkel"
    os.environ["INNTAK_STI"] = "/tmp/claude-0/-home-user-nav/2aa279d8-cc12-5cc4-8948-e73c80a873c2/scratchpad/inntak"
    # NB: appen importerer ruterne som «ruter.last_opp» (via tjenester/api
    # på sys.path) — bruk samme modulnavn her, ellers patches feil instans.
    import ruter.last_opp as lo
    lo.INNTAK_STI = os.environ["INNTAK_STI"]
    from fastapi.testclient import TestClient
    import hoved
    hoved.API_NOKKEL = "test-nokkel"
    return TestClient(hoved.app)


def _ny_jobb(pg, state="QUEUED", fil_sti="/tmp/finnes-ikke.pdf", **felter) -> str:
    job_id = str(uuid.uuid4())
    kolonner = {"job_id": job_id, "idempotency_key": job_id, "state": state,
                "file_name": "test.pdf", "file_path": fil_sti, **felter}
    navn = ", ".join(kolonner)
    plasser = ", ".join(["%s"] * len(kolonner))
    with pg.cursor() as cur:
        cur.execute(f"INSERT INTO jobs ({navn}) VALUES ({plasser})",
                    list(kolonner.values()))
    pg.commit()
    return job_id


def _state(pg, job_id) -> str:
    with pg.cursor() as cur:
        cur.execute("SELECT state FROM jobs WHERE job_id = %s", (job_id,))
        return cur.fetchone()[0]


def _sett_resultat(pg, job_id, kolonne, verdi):
    import psycopg2.extras
    with pg.cursor() as cur:
        cur.execute(
            f"INSERT INTO results (job_id, {kolonne}) VALUES (%s, %s) "
            f"ON CONFLICT (job_id) DO UPDATE SET {kolonne} = EXCLUDED.{kolonne}",
            (job_id, psycopg2.extras.Json(verdi)),
        )
    pg.commit()


# ------------------------------------------------------------------ #
#  1. API: helse, auth, opplasting, idempotens                        #
# ------------------------------------------------------------------ #

def test_helse_er_aapen_uten_nokkel(api_klient):
    svar = api_klient.get("/helse")
    assert svar.status_code == 200


def test_endepunkt_krever_api_nokkel(api_klient):
    svar = api_klient.get("/jobb/123")
    assert svar.status_code == 401


def test_feil_api_nokkel_avvises(api_klient):
    svar = api_klient.get("/jobb/123", headers={"X-API-Key": "feil"})
    assert svar.status_code == 401


def test_ikke_pdf_avvises(api_klient):
    svar = api_klient.post(
        "/last-opp/",
        files={"fil": ("test.txt", io.BytesIO(b"hei"), "text/plain")},
        headers={"X-API-Key": "test-nokkel"},
    )
    assert svar.status_code == 400


def test_opplasting_full_flyt(api_klient, pg, rc):
    from config.config_loader import CONFIG
    svar = api_klient.post(
        "/last-opp/",
        files={"fil": ("test.pdf", io.BytesIO(MINI_PDF), "application/pdf")},
        headers={"X-API-Key": "test-nokkel"},
    )
    assert svar.status_code == 202
    kropp = svar.json()
    job_id = kropp["job_id"]
    assert kropp["state"] == "QUEUED"
    assert kropp["idempotent"] is False

    # Postgres: tilstand + audit
    assert _state(pg, job_id) == "QUEUED"
    med = api_klient.get(f"/audit/{job_id}", headers={"X-API-Key": "test-nokkel"})
    hendelser = [r["event_type"] for r in med.json()]
    assert "OPPRETTET" in hendelser
    assert "STATE_ENDRING" in hendelser

    # Redis: nøyaktig én melding i preprocess-køen
    ko = CONFIG["redis"]["kooer"]["preprocess"]
    assert rc.llen(ko) == 1
    payload = json.loads(rc.lindex(ko, 0))
    assert payload["job_id"] == job_id

    # Filen er faktisk lagret
    assert os.path.exists(payload["fil_sti"])


def test_idempotent_opplasting_gir_samme_jobb(api_klient, rc):
    from config.config_loader import CONFIG
    fil = {"fil": ("test.pdf", io.BytesIO(MINI_PDF), "application/pdf")}
    hodene = {"X-API-Key": "test-nokkel"}
    forste = api_klient.post("/last-opp/", files=fil, headers=hodene).json()
    fil = {"fil": ("test.pdf", io.BytesIO(MINI_PDF), "application/pdf")}
    andre = api_klient.post("/last-opp/", files=fil, headers=hodene)
    assert andre.status_code == 200
    assert andre.json()["idempotent"] is True
    assert andre.json()["job_id"] == forste["job_id"]
    # Ingen duplikat i køen
    assert rc.llen(CONFIG["redis"]["kooer"]["preprocess"]) == 1


def test_metrics_endepunkt_er_aapent_og_teller(api_klient):
    """Prometheus skal kunne scrape /metrics uten nøkkel."""
    api_klient.get("/helse")
    svar = api_klient.get("/metrics")
    assert svar.status_code == 200
    assert b"nav_api_forespoersler_total" in svar.content


def test_jobb_og_resultat_404(api_klient):
    ukjent = str(uuid.uuid4())
    hodene = {"X-API-Key": "test-nokkel"}
    assert api_klient.get(f"/jobb/{ukjent}", headers=hodene).status_code == 404
    assert api_klient.get(f"/resultat/{ukjent}", headers=hodene).status_code == 404


def test_ugyldig_uuid_gir_422_ikke_500(api_klient):
    """M7: rå streng i job_id skal valideres — ikke smelle i Postgres."""
    hodene = {"X-API-Key": "test-nokkel"}
    for sti in ["/jobb/ikke-en-uuid", "/resultat/abc",
                "/resultat/abc/felter", "/audit/'; DROP TABLE jobs;--"]:
        svar = api_klient.get(sti, headers=hodene)
        assert svar.status_code == 422, f"{sti} ga {svar.status_code}"


def test_h2_samtidig_opplasting_gir_ikke_500(api_klient, pg, monkeypatch):
    """H2: taper INSERT-kappløpet → idempotent svar/409, aldri 500,
    og ingen foreldreløs fil på disk."""
    import ruter.last_opp as lo
    nokkel = lo._idempotens_nokkel(MINI_PDF)
    _ny_jobb(pg, idempotency_key=nokkel)

    # Simuler kappløpet: SELECT-sjekken ser ingenting, INSERT kolliderer
    monkeypatch.setattr(lo, "_idempotent_svar", lambda pg, k: None)

    inntak = lo.INNTAK_STI
    antall_foer = len(os.listdir(inntak)) if os.path.isdir(inntak) else 0
    svar = api_klient.post(
        "/last-opp/",
        files={"fil": ("test.pdf", io.BytesIO(MINI_PDF), "application/pdf")},
        headers={"X-API-Key": "test-nokkel"},
    )
    assert svar.status_code == 409
    antall_etter = len(os.listdir(inntak)) if os.path.isdir(inntak) else 0
    assert antall_etter == antall_foer, "foreldreløs fil etterlatt på disk"


def test_redis_nede_ved_opplasting_gjenopprettes_av_ghost_detektor(api_klient, pg, rc, monkeypatch):
    """
    REL-1-scenario: Postgres committes FØR Redis-push. Feiler pushen,
    får klienten 500, men jobben ligger trygt som QUEUED og plukkes
    opp av ghost-detektoren i neste reconciliation-runde.
    """
    import ruter.last_opp as lo

    def _redis_nede():
        raise ConnectionError("redis er nede")

    monkeypatch.setattr(lo, "_redis_client", _redis_nede)
    svar = api_klient.post(
        "/last-opp/",
        files={"fil": ("test.pdf", io.BytesIO(MINI_PDF), "application/pdf")},
        headers={"X-API-Key": "test-nokkel"},
    )
    assert svar.status_code == 500

    # Jobben finnes og er QUEUED — ingen data tapt
    with pg.cursor() as cur:
        cur.execute("SELECT job_id, state FROM jobs")
        rad = cur.fetchone()
    assert rad is not None
    job_id, state = str(rad[0]), rad[1]
    assert state == "QUEUED"

    # Ghost-detektoren re-køer jobben når Redis er tilbake
    from config.config_loader import CONFIG
    from tjenester.workers.reconciliation.reconciliation_worker import ReconciliationWorker
    with pg.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET updated_at = NOW() - INTERVAL '30 minutes' WHERE job_id = %s",
            (job_id,),
        )
    pg.commit()
    ReconciliationWorker().reparer_ghost_states(pg)
    ko = CONFIG["redis"]["kooer"]["preprocess"]
    assert rc.llen(ko) == 1
    assert json.loads(rc.lindex(ko, 0))["job_id"] == job_id


# ------------------------------------------------------------------ #
#  2. Tilstandsmaskin og låsing                                        #
# ------------------------------------------------------------------ #

def test_ulovlig_tilstandsovergang_avvises(pg):
    from tjenester.workers.lag0_preprocessing.lag0 import PreprocessingWorker
    from tjenester.workers.base_worker import UgyldigTilstandsovergang
    worker = PreprocessingWorker()
    job_id = _ny_jobb(pg, state="DONE")
    with pytest.raises(UgyldigTilstandsovergang):
        worker._oppdater_state(job_id, "PREPROCESSING", pg)
    pg.rollback()


def test_las_hindrer_dobbel_behandling(pg):
    import psycopg2
    from tjenester.workers.lag0_preprocessing.lag0 import PreprocessingWorker
    worker = PreprocessingWorker()
    job_id = _ny_jobb(pg)
    assert worker._las_jobb(job_id, pg) is True
    pg.commit()
    with psycopg2.connect(PG_URL) as pg2:
        assert worker._las_jobb(job_id, pg2) is False


# ------------------------------------------------------------------ #
#  3. PreprocessingWorker ende-til-ende (ekte Postgres + Redis)        #
# ------------------------------------------------------------------ #

def test_preprocessing_worker_full_behandling(pg, rc):
    from config.config_loader import CONFIG
    from tjenester.workers.lag0_preprocessing.lag0 import PreprocessingWorker
    worker = PreprocessingWorker()
    job_id = _ny_jobb(pg)

    worker._behandle({"job_id": job_id, "fil_sti": "/tmp/finnes-ikke.pdf"})

    assert _state(pg, job_id) == "OCR_PROCESSING"
    with pg.cursor() as cur:
        cur.execute("SELECT preprocess_result FROM results WHERE job_id = %s", (job_id,))
        resultat = cur.fetchone()[0]
    assert resultat["job_id"] == job_id
    assert "quality_score" in resultat

    # Neste kø har fått payload med forrige_resultat
    ko = CONFIG["redis"]["kooer"]["ocr"]
    assert rc.llen(ko) == 1
    payload = json.loads(rc.lindex(ko, 0))
    assert payload["forrige_resultat"]["job_id"] == job_id

    # Låsen er frigitt
    with pg.cursor() as cur:
        cur.execute("SELECT locked_by FROM jobs WHERE job_id = %s", (job_id,))
        assert cur.fetchone()[0] is None


def test_ocr_worker_fallback_uten_modeller(pg, rc):
    """
    OCRWorker uten paddleocr/TrOCR: degraderer til konfidens 0.0,
    fortsetter til NLP_PROCESSING og flagger for manuell gjennomgang.
    """
    from config.config_loader import CONFIG
    from tjenester.workers.lag1_ocr.lag1 import OCRWorker
    worker = OCRWorker()
    job_id = _ny_jobb(pg, state="PREPROCESSING")
    forrige = {
        "schema_version": 1, "job_id": job_id, "document_type": "trykt",
        "quality_score": 0.9, "quality_approved": True,
        "preprocessed_path": "/tmp/finnes-ikke.pdf", "rejection_reason": None,
    }

    worker._behandle({"job_id": job_id, "fil_sti": "/tmp/finnes-ikke.pdf",
                      "forrige_resultat": forrige})

    assert _state(pg, job_id) == "NLP_PROCESSING"
    with pg.cursor() as cur:
        cur.execute("SELECT ocr_result FROM results WHERE job_id = %s", (job_id,))
        resultat = cur.fetchone()[0]
    assert resultat["confidence_approved"] is False
    assert rc.llen(CONFIG["redis"]["kooer"]["nlp"]) == 1


# ------------------------------------------------------------------ #
#  4. RoutingWorker: APPROVED og REVIEW                                #
# ------------------------------------------------------------------ #

def _routing_jobb(pg, nlp_endringer=None) -> tuple:
    from tjenester.workers.lag3_routing.lag3 import RoutingWorker
    worker = RoutingWorker()
    job_id = _ny_jobb(pg, state="NLP_PROCESSING")
    nlp = dict(GYLDIG_NLP_RESULTAT, job_id=job_id, **(nlp_endringer or {}))
    return worker, job_id, nlp


def test_routing_approved(pg):
    worker, job_id, nlp = _routing_jobb(pg)
    worker._behandle({"job_id": job_id, "fil_sti": "", "forrige_resultat": nlp})
    assert _state(pg, job_id) == "DONE"
    with pg.cursor() as cur:
        cur.execute("SELECT routing_decision FROM results WHERE job_id = %s", (job_id,))
        assert cur.fetchone()[0] == "APPROVED"


def test_routing_review_ved_lav_ocr_konfidens(pg):
    worker, job_id, nlp = _routing_jobb(pg, {"ocr_confidence": 0.10})
    worker._behandle({"job_id": job_id, "fil_sti": "", "forrige_resultat": nlp})
    assert _state(pg, job_id) == "DONE"
    with pg.cursor() as cur:
        cur.execute(
            "SELECT routing_decision, label_studio_project FROM results WHERE job_id = %s",
            (job_id,),
        )
        beslutning, prosjekt = cur.fetchone()
    assert beslutning == "REVIEW"
    assert prosjekt is not None


def test_routing_review_ved_anomali(pg):
    worker, job_id, nlp = _routing_jobb(
        pg, {"anomaly": {"har_anomali": True, "anomali_score": 0.9, "detaljer": ["x"]}}
    )
    worker._behandle({"job_id": job_id, "fil_sti": "", "forrige_resultat": nlp})
    with pg.cursor() as cur:
        cur.execute("SELECT routing_decision FROM results WHERE job_id = %s", (job_id,))
        assert cur.fetchone()[0] == "REVIEW"


# ------------------------------------------------------------------ #
#  5. Retry og DLQ                                                     #
# ------------------------------------------------------------------ #

def test_feil_gir_retry_med_okt_teller(pg, rc, monkeypatch):
    from config.config_loader import CONFIG
    from tjenester.workers.lag0_preprocessing.lag0 import PreprocessingWorker
    worker = PreprocessingWorker()
    monkeypatch.setattr(PreprocessingWorker, "process",
                        lambda self, job, pg: (_ for _ in ()).throw(ValueError("smell")))
    job_id = _ny_jobb(pg)

    worker._behandle({"job_id": job_id, "fil_sti": "x", "retry_count": 0})

    ko = CONFIG["redis"]["kooer"]["preprocess"]
    assert rc.llen(ko) == 1
    payload = json.loads(rc.lindex(ko, 0))
    assert payload["retry_count"] == 1
    # Jobben er IKKE FAILED ennå
    assert _state(pg, job_id) == "PREPROCESSING"


def test_uttomte_retries_gir_dlq_og_failed(pg, rc, monkeypatch):
    from tjenester.workers.lag0_preprocessing.lag0 import PreprocessingWorker
    worker = PreprocessingWorker()
    monkeypatch.setattr(PreprocessingWorker, "process",
                        lambda self, job, pg: (_ for _ in ()).throw(ValueError("smell")))
    job_id = _ny_jobb(pg)

    worker._behandle({"job_id": job_id, "fil_sti": "x", "retry_count": 3})

    assert _state(pg, job_id) == "FAILED"
    with pg.cursor() as cur:
        cur.execute("SELECT error_type FROM dead_letter_queue WHERE job_id = %s", (job_id,))
        assert cur.fetchone()[0] == "ValueError"
        cur.execute(
            "SELECT count(*) FROM audit_log WHERE job_id = %s AND event_type = 'DLQ'",
            (job_id,),
        )
        assert cur.fetchone()[0] == 1
    assert rc.llen(worker.dlq_name) == 1


def test_c1_las_frigis_ved_feil_saa_retry_kan_plukkes(pg, monkeypatch):
    """C1: etter feil skal låsen være frigitt — retry-meldingen skal
    ikke konsumeres og forkastes av en fortsatt aktiv lås."""
    from tjenester.workers.lag0_preprocessing.lag0 import PreprocessingWorker
    worker = PreprocessingWorker()
    monkeypatch.setattr(PreprocessingWorker, "process",
                        lambda self, job, pg: (_ for _ in ()).throw(ValueError("smell")))
    job_id = _ny_jobb(pg)

    worker._behandle({"job_id": job_id, "fil_sti": "x", "retry_count": 0})

    with pg.cursor() as cur:
        cur.execute("SELECT locked_by, attempt_count, last_error FROM jobs WHERE job_id = %s",
                    (job_id,))
        locked_by, forsok, siste_feil = cur.fetchone()
    assert locked_by is None, "låsen må være frigitt etter feil"
    assert forsok == 1, "attempt_count skal telles varig i Postgres"
    assert "smell" in siste_feil


def test_c1_giftig_jobb_naar_dlq_selv_uten_payload_teller(pg, monkeypatch):
    """C1: simulerer reconciliation-re-kø der payload-telleren er tapt —
    databasens attempt_count skal likevel drive jobben til DLQ."""
    from tjenester.workers.lag0_preprocessing.lag0 import PreprocessingWorker
    worker = PreprocessingWorker()
    monkeypatch.setattr(PreprocessingWorker, "process",
                        lambda self, job, pg: (_ for _ in ()).throw(ValueError("gift")))
    job_id = _ny_jobb(pg, attempt_count=5)

    worker._behandle({"job_id": job_id, "fil_sti": "x", "retry_count": 0})

    assert _state(pg, job_id) == "FAILED"
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM dead_letter_queue WHERE job_id = %s", (job_id,))
        assert cur.fetchone()[0] == 1


# ------------------------------------------------------------------ #
#  6. Reconciliation: stuck, ghost og tapte jobber                     #
# ------------------------------------------------------------------ #

def test_reconciliation_stuck_jobb_re_koes(pg, rc):
    from config.config_loader import CONFIG
    from tjenester.workers.reconciliation.reconciliation_worker import ReconciliationWorker
    rw = ReconciliationWorker()
    job_id = _ny_jobb(pg, state="OCR_PROCESSING", locked_by="dod-worker")
    with pg.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET lock_expiry = NOW() - INTERVAL '5 minutes' WHERE job_id = %s",
            (job_id,),
        )
    pg.commit()
    _sett_resultat(pg, job_id, "preprocess_result", {"job_id": job_id})

    antall = rw.reparer_stuck_jobs(pg)

    assert antall == 1
    assert rc.llen(CONFIG["redis"]["kooer"]["ocr"]) == 1
    with pg.cursor() as cur:
        cur.execute("SELECT locked_by FROM jobs WHERE job_id = %s", (job_id,))
        assert cur.fetchone()[0] is None


def test_reconciliation_ghost_re_koes(pg, rc):
    from config.config_loader import CONFIG
    from tjenester.workers.reconciliation.reconciliation_worker import ReconciliationWorker
    rw = ReconciliationWorker()
    job_id = _ny_jobb(pg, state="QUEUED")
    with pg.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET updated_at = NOW() - INTERVAL '30 minutes' WHERE job_id = %s",
            (job_id,),
        )
    pg.commit()

    antall = rw.reparer_ghost_states(pg)

    assert antall == 1
    assert rc.llen(CONFIG["redis"]["kooer"]["preprocess"]) == 1
    with pg.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM audit_log WHERE job_id = %s "
            "AND event_type = 'RECONCILIATION_GHOST'",
            (job_id,),
        )
        assert cur.fetchone()[0] == 1


def test_reconciliation_tapt_jobb_blir_queued(pg, rc):
    from tjenester.workers.reconciliation.reconciliation_worker import ReconciliationWorker
    rw = ReconciliationWorker()
    job_id = _ny_jobb(pg, state="UPLOADED")
    with pg.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET created_at = NOW() - INTERVAL '30 minutes' WHERE job_id = %s",
            (job_id,),
        )
    pg.commit()

    antall = rw.reparer_tapte_jobber(pg)

    assert antall == 1
    assert _state(pg, job_id) == "QUEUED"


# ------------------------------------------------------------------ #
#  7. kfp_steg (kubeflow-modus): uten kø, med DLQ ved feil             #
# ------------------------------------------------------------------ #

def test_kfp_steg_preprocess_uten_ko(pg, rc):
    from config.config_loader import CONFIG
    from tjenester.workers.kfp_steg import kjor_steg
    job_id = _ny_jobb(pg)

    kjor_steg("preprocess", job_id)

    assert _state(pg, job_id) == "OCR_PROCESSING"
    with pg.cursor() as cur:
        cur.execute("SELECT preprocess_result FROM results WHERE job_id = %s", (job_id,))
        assert cur.fetchone()[0]["job_id"] == job_id
    # KFP orkestrerer — ingenting skal ligge i Redis-køene
    assert rc.llen(CONFIG["redis"]["kooer"]["ocr"]) == 0


def test_kfp_steg_routing_fra_results_tabellen(pg):
    from tjenester.workers.kfp_steg import kjor_steg
    job_id = _ny_jobb(pg, state="NLP_PROCESSING")
    _sett_resultat(pg, job_id, "nlp_result", dict(GYLDIG_NLP_RESULTAT, job_id=job_id))

    kjor_steg("routing", job_id)

    assert _state(pg, job_id) == "DONE"
    with pg.cursor() as cur:
        cur.execute("SELECT routing_decision FROM results WHERE job_id = %s", (job_id,))
        assert cur.fetchone()[0] == "APPROVED"


def test_kfp_steg_re_kjoring_er_ufarlig(pg):
    from tjenester.workers.kfp_steg import kjor_steg
    job_id = _ny_jobb(pg)
    kjor_steg("preprocess", job_id)
    # Re-kjøring (f.eks. KFP-retry): skal ikke krasje og ikke endre tilstand
    kjor_steg("preprocess", job_id)
    assert _state(pg, job_id) == "OCR_PROCESSING"


def test_kfp_steg_feil_gir_dlq_og_reises(pg, monkeypatch):
    from tjenester.workers.lag0_preprocessing.lag0 import PreprocessingWorker
    from tjenester.workers.kfp_steg import kjor_steg
    monkeypatch.setattr(PreprocessingWorker, "process",
                        lambda self, job, pg: (_ for _ in ()).throw(RuntimeError("smell")))
    job_id = _ny_jobb(pg)

    with pytest.raises(RuntimeError):
        kjor_steg("preprocess", job_id)

    assert _state(pg, job_id) == "FAILED"
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM dead_letter_queue WHERE job_id = %s", (job_id,))
        assert cur.fetchone()[0] == 1


def test_kfp_steg_mangler_forrige_resultat_gir_feil(pg):
    from tjenester.workers.kfp_steg import kjor_steg
    job_id = _ny_jobb(pg, state="NLP_PROCESSING")
    with pytest.raises(ValueError):
        kjor_steg("routing", job_id)


# ------------------------------------------------------------------ #
#  8. UiPath-kontrakten: /resultat/{id}/felter                         #
# ------------------------------------------------------------------ #

def test_felter_endepunkt_full_robotflyt(api_klient, pg):
    """Samme flyt som UiPath-roboten: jobb → DONE → flate felter."""
    from tjenester.workers.kfp_steg import kjor_steg
    job_id = _ny_jobb(pg, state="NLP_PROCESSING")
    _sett_resultat(pg, job_id, "nlp_result", dict(GYLDIG_NLP_RESULTAT, job_id=job_id))
    kjor_steg("routing", job_id)

    svar = api_klient.get(f"/resultat/{job_id}/felter",
                          headers={"X-API-Key": "test-nokkel"})
    assert svar.status_code == 200
    kropp = svar.json()
    assert kropp["ferdig"] is True
    assert kropp["beslutning"] == "APPROVED"
    assert kropp["felter"]["navn"] == "Ola Nordmann"
    assert kropp["felter"]["ytelse"] == "dagpenger"
    assert kropp["felter"]["fylke"] == "Oslo"
    assert kropp["konfidens"]["ocr"] == 0.97
    assert kropp["gjennomgang"]["kreves"] is False

    # M11: terminal tilstand skal sette completed_at (SLA-rapportering)
    with pg.cursor() as cur:
        cur.execute("SELECT completed_at FROM jobs WHERE job_id = %s", (job_id,))
        assert cur.fetchone()[0] is not None


def test_felter_409_foer_ferdig(api_klient, pg):
    job_id = _ny_jobb(pg, state="QUEUED")
    svar = api_klient.get(f"/resultat/{job_id}/felter",
                          headers={"X-API-Key": "test-nokkel"})
    assert svar.status_code == 409
    assert svar.json()["ferdig"] is False
    assert svar.json()["state"] == "QUEUED"


def test_felter_404_for_ukjent_jobb(api_klient):
    svar = api_klient.get(f"/resultat/{uuid.uuid4()}/felter",
                          headers={"X-API-Key": "test-nokkel"})
    assert svar.status_code == 404


def test_felter_gjennomgang_kreves_ved_review(api_klient, pg):
    from tjenester.workers.kfp_steg import kjor_steg
    job_id = _ny_jobb(pg, state="NLP_PROCESSING")
    _sett_resultat(pg, job_id, "nlp_result",
                   dict(GYLDIG_NLP_RESULTAT, job_id=job_id, ocr_confidence=0.10))
    kjor_steg("routing", job_id)

    kropp = api_klient.get(f"/resultat/{job_id}/felter",
                           headers={"X-API-Key": "test-nokkel"}).json()
    assert kropp["beslutning"] == "REVIEW"
    assert kropp["gjennomgang"]["kreves"] is True
    assert kropp["gjennomgang"]["label_studio_prosjekt"] is not None


# ------------------------------------------------------------------ #
#  9. rebuild_redis: Postgres er sannheten                             #
# ------------------------------------------------------------------ #

def _kjor_rebuild():
    import subprocess
    miljo = dict(os.environ, POSTGRES_URL=PG_URL)
    resultat = subprocess.run(
        [sys.executable, "skript/rebuild_redis.py"],
        capture_output=True, text=True, env=miljo, cwd=".",
    )
    assert resultat.returncode == 0, resultat.stderr


def test_rebuild_redis_gjenoppretter_koer_med_full_kontrakt(pg, rc):
    """C2: payloaden må følge worker-kontrakten — fil_sti + retry_count."""
    from config.config_loader import CONFIG
    job_id = _ny_jobb(pg, state="QUEUED", fil_sti="/data/inntak/x.pdf",
                      attempt_count=2)
    rc.flushdb()

    _kjor_rebuild()

    ko = CONFIG["redis"]["kooer"]["preprocess"]
    assert rc.llen(ko) == 1
    payload = json.loads(rc.lindex(ko, 0))
    assert payload["job_id"] == job_id
    assert payload["fil_sti"] == "/data/inntak/x.pdf"
    assert payload["retry_count"] == 2


def test_rebuild_redis_inkluderer_forrige_resultat(pg, rc):
    """C2: OCR-jobber må re-køes MED preprocess_result — ellers DLQ-løkke."""
    from config.config_loader import CONFIG
    job_id = _ny_jobb(pg, state="OCR_PROCESSING")
    _sett_resultat(pg, job_id, "preprocess_result", {"job_id": job_id, "document_type": "trykt"})
    rc.flushdb()

    _kjor_rebuild()

    ko = CONFIG["redis"]["kooer"]["ocr"]
    assert rc.llen(ko) == 1
    payload = json.loads(rc.lindex(ko, 0))
    assert payload["forrige_resultat"]["document_type"] == "trykt"


def test_rebuild_redis_markerer_inkonsistente_failed(pg, rc):
    """C2: OCR-jobb UTEN preprocess_result skal bli FAILED, ikke re-køet."""
    from config.config_loader import CONFIG
    job_id = _ny_jobb(pg, state="OCR_PROCESSING")   # ingen results-rad
    rc.flushdb()

    _kjor_rebuild()

    assert rc.llen(CONFIG["redis"]["kooer"]["ocr"]) == 0
    assert _state(pg, job_id) == "FAILED"
    with pg.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM audit_log WHERE job_id = %s "
            "AND event_type = 'DATA_INKONSISTENS'", (job_id,))
        assert cur.fetchone()[0] == 1
