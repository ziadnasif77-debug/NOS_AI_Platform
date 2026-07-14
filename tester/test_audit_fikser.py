"""
Regresjonstester for andre-runde-auditfunnene (C1-C2, H1-H4, M1-M11, L1-L5).
Ren logikk + kildebaserte sjekker — de tunge scenarioene dekkes i
test_integrasjon_lokal.py.
"""
import sys
sys.path.insert(0, ".")
import os
from pathlib import Path

import pytest

BASE_WORKER = Path("tjenester/workers/base_worker.py").read_text(encoding="utf-8")
RECONCILIATION = Path("tjenester/workers/reconciliation/reconciliation_worker.py").read_text(encoding="utf-8")
REBUILD = Path("skript/rebuild_redis.py").read_text(encoding="utf-8")
LAST_OPP = Path("tjenester/api/ruter/last_opp.py").read_text(encoding="utf-8")
SOK_HOVED = Path("tjenester/sok/hoved.py").read_text(encoding="utf-8")
LAG3 = Path("tjenester/workers/lag3_routing/lag3.py").read_text(encoding="utf-8")
COMPOSE = Path("docker-compose.yml").read_text(encoding="utf-8")


# ------------------------------------------------------------------ #
#  C1: lås + varig forsøkstelling                                      #
# ------------------------------------------------------------------ #

def test_c1_las_frigis_foer_retry_re_koe():
    retry_del = BASE_WORKER[BASE_WORKER.index("def _haandter_feil"):]
    frigi = retry_del.index("_frigi_las")
    rpush = retry_del.index("rpush")
    assert frigi < rpush, "låsen må frigis FØR retry-meldingen re-køes"


def test_c1_attempt_count_er_varig():
    assert "attempt_count = attempt_count + 1" in BASE_WORKER
    assert "RETURNING attempt_count" in BASE_WORKER
    assert "last_error" in BASE_WORKER


def test_c1_dlq_naas_selv_uten_payload_teller():
    # Beslutningen må også se på databasens teller (db_forsok)
    assert "db_forsok <= max_retries" in BASE_WORKER


def test_c1_reconciliation_payload_baerer_telleren():
    assert '"retry_count": attempt_count' in RECONCILIATION
    assert "attempt_count=rad.get" in RECONCILIATION


# ------------------------------------------------------------------ #
#  C2: rebuild_redis med korrekt kontrakt                              #
# ------------------------------------------------------------------ #

def test_c2_rebuild_payload_har_full_kontrakt():
    assert '"fil_sti"' in REBUILD
    assert '"retry_count"' in REBUILD
    assert "forrige_resultat" in REBUILD


def test_c2_rebuild_markerer_inkonsistente_som_failed():
    assert "DATA_INKONSISTENS" in REBUILD
    assert "FAILED" in REBUILD


# ------------------------------------------------------------------ #
#  H1: søket returnerer komplette dokumenter                           #
# ------------------------------------------------------------------ #

class _FalskEntity:
    def __init__(self, felter):
        self._felter = felter

    def get(self, navn):
        return self._felter.get(navn)


class _FalskTreff:
    def __init__(self, felter):
        self.entity = _FalskEntity(felter)


def test_h1_rrf_returnerer_dokumenter_ikke_bare_ider():
    from tjenester.sok.fusjon import rrf_fusjoner
    vektor = [_FalskTreff({"fil_id": "a", "tekst": "vedtak om dagpenger",
                           "navn": "Ola", "filnavn": "a.pdf", "side_nummer": 0,
                           "dato": "2020", "ytelse": "dagpenger",
                           "fylke": "Oslo", "dokumenttype": "vedtak"})]
    bm25_dok = [{"fil_id": "b", "tekst": "sykepenger for Kari"}]
    resultat = rrf_fusjoner(vektor, [0], bm25_dok)
    assert len(resultat) == 2
    a = next(r for r in resultat if r["fil_id"] == "a")
    assert a["navn"] == "Ola" and a["utdrag"].startswith("vedtak")
    assert "score" in a
    b = next(r for r in resultat if r["fil_id"] == "b")
    assert b["utdrag"] == "sykepenger for Kari"   # BM25-only: tekst fra korpus


def test_h1_dokument_i_begge_kilder_far_hoyest_score():
    from tjenester.sok.fusjon import rrf_fusjoner
    vektor = [_FalskTreff({"fil_id": "felles", "tekst": "x"}),
              _FalskTreff({"fil_id": "kun-vektor", "tekst": "y"})]
    bm25_dok = [{"fil_id": "felles", "tekst": "x"}]
    resultat = rrf_fusjoner(vektor, [0], bm25_dok)
    assert resultat[0]["fil_id"] == "felles"


# ------------------------------------------------------------------ #
#  H2/M7/L2: opplastings-robusthet                                     #
# ------------------------------------------------------------------ #

def test_h2_unik_kollisjon_haandteres():
    assert "UniqueViolation" in LAST_OPP
    assert "committet" in LAST_OPP   # rydder kun ukommitterte filer


def test_m7_uuid_validering_paa_alle_oppslag():
    assert LAST_OPP.count("_valider_job_id(job_id)") >= 4


# ------------------------------------------------------------------ #
#  H4: statuspropagering                                               #
# ------------------------------------------------------------------ #

def test_h4_sok_ruter_propagerer_status():
    src = Path("tjenester/api/ruter/sok.py").read_text(encoding="utf-8")
    assert "status_code=svar.status_code" in src
    assert "fodselsnummer" not in src   # utdatert filter-omtale fjernet


# ------------------------------------------------------------------ #
#  M1/M2: BM25 lazy rebuild + idempotent indeksering                   #
# ------------------------------------------------------------------ #

def test_m1_bm25_lazy_rebuild():
    assert "_bm25_skitten" in SOK_HOVED
    # Ingen full rebuild i indekser-endepunktet
    indekser_del = SOK_HOVED[SOK_HOVED.index("def indekser"):SOK_HOVED.index("def sok")]
    assert "BM25Okapi(" not in indekser_del


def test_m2_indeksering_er_idempotent():
    assert "_samling.delete" in SOK_HOVED
    assert 'raise HTTPException(status_code=400, detail="Ugyldig fil_id")' in SOK_HOVED


# ------------------------------------------------------------------ #
#  M3: avgrenset indekseringspool + varig feilspor                     #
# ------------------------------------------------------------------ #

def test_m3_avgrenset_pool_og_feilspor():
    assert "ThreadPoolExecutor" in LAG3
    assert "INDEKSERING_FEILET" in LAG3
    assert "threading.Thread" not in LAG3


# ------------------------------------------------------------------ #
#  M4: kubeflow-gjenoppretting i reconciliation                        #
# ------------------------------------------------------------------ #

def test_m4_reconciliation_stotter_kubeflow_modus():
    assert "_send_videre" in RECONCILIATION
    assert "create_run_from_pipeline_package" in RECONCILIATION


# ------------------------------------------------------------------ #
#  M5/M6/M8/H3: infrastruktur                                          #
# ------------------------------------------------------------------ #

def test_m5_integrasjonstester_har_produksjonsvakt():
    src = Path("tester/test_integrasjon_lokal.py").read_text(encoding="utf-8")
    assert "localhost" in src.split("MINI_PDF")[0]
    assert "RuntimeError" in src.split("MINI_PDF")[0]


def test_m6_ci_workflow_finnes():
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "INTEGRASJONSTEST" in ci
    assert "postgres:16" in ci


def test_m8_cors_kan_konfigureres():
    src = Path("tjenester/api/hoved.py").read_text(encoding="utf-8")
    assert 'os.environ.get("CORS_ORIGINS"' in src


def test_h3_legacy_tjenester_bak_profil():
    for tjeneste in ["lag0", "lag1", "lag2", "lag3", "lag4", "lag5", "ruter"]:
        blokk_start = COMPOSE.index(f"\n  {tjeneste}:\n")
        blokk = COMPOSE[blokk_start:blokk_start + 120]
        assert "profiles: [legacy]" in blokk, f"{tjeneste} mangler legacy-profil"


# ------------------------------------------------------------------ #
#  M9: OIDC-autorisasjon (rolle-claim)                                 #
# ------------------------------------------------------------------ #

def test_m9_paakrevd_rolle_haandheves(monkeypatch):
    import delt.autentisering as auth
    monkeypatch.setenv("AUTH_MODUS", "oidc")
    monkeypatch.setenv("OIDC_PAAKREVD_ROLLE", "arkiv-bruker")
    monkeypatch.setattr(auth, "valider_oidc_token",
                        lambda token: {"sub": "x", "roles": ["annet"]})
    assert auth.sjekk_forespoersel({"Authorization": "Bearer t"}, "") == "Manglende rolle"

    monkeypatch.setattr(auth, "valider_oidc_token",
                        lambda token: {"sub": "x", "roles": ["arkiv-bruker"]})
    assert auth.sjekk_forespoersel({"Authorization": "Bearer t"}, "") is None


def test_m9_uten_rollekrav_holder_gyldig_token(monkeypatch):
    import delt.autentisering as auth
    monkeypatch.setenv("AUTH_MODUS", "oidc")
    monkeypatch.delenv("OIDC_PAAKREVD_ROLLE", raising=False)
    monkeypatch.setattr(auth, "valider_oidc_token", lambda token: {"sub": "x"})
    assert auth.sjekk_forespoersel({"Authorization": "Bearer t"}, "") is None


# ------------------------------------------------------------------ #
#  M11/L1/L5: opprydding                                               #
# ------------------------------------------------------------------ #

def test_m11_completed_at_settes_ved_terminal_tilstand():
    assert "completed_at = NOW()" in BASE_WORKER


def test_l1_gpu_semafor_fjernet():
    lag1 = Path("tjenester/workers/lag1_ocr/lag1.py").read_text(encoding="utf-8")
    assert "Semaphore" not in lag1


def test_l5_logging_uten_duplikate_handlers():
    from delt.verktøy import konfigurer_logging
    a = konfigurer_logging("test-tjeneste-x")
    b = konfigurer_logging("test-tjeneste-x")
    assert a is b
    assert len(a.handlers) == 1
