"""
Tester for kubeflow-modus: kfp_steg-kjøreren, API-gating på KJOREMODUS,
env-overrides i config_loader og at manifester/pipelines er konsistente.

Kildebaserte tester (samme stil som test_hardening.py) siden psycopg2/kfp
ikke er tilgjengelig i testmiljøet.
"""
import sys
sys.path.insert(0, ".")
import re
from pathlib import Path

import yaml

KFP_STEG = Path("tjenester/workers/kfp_steg.py").read_text(encoding="utf-8")
LAST_OPP = Path("tjenester/api/ruter/last_opp.py").read_text(encoding="utf-8")
CONFIG_LOADER = Path("config/config_loader.py").read_text(encoding="utf-8")
DOKUMENT_PIPELINE = Path("kubeflow/dokument_pipeline.py").read_text(encoding="utf-8")
API_DOCKERFILE = Path("tjenester/api/Dockerfile").read_text(encoding="utf-8")
API_KRAV = Path("tjenester/api/krav.txt").read_text(encoding="utf-8")


# ------------------------------------------------------------------ #
#  kfp_steg                                                            #
# ------------------------------------------------------------------ #

def test_steg_map_dekker_alle_fire_steg():
    for steg in ["preprocess", "ocr", "nlp", "routing"]:
        assert f'"{steg}":' in KFP_STEG, f"steg '{steg}' mangler i STEG_MAP"


def test_steg_map_forrige_kolonner():
    # preprocess har ingen forrige, resten leser forrige stegs kolonne
    assert '"PreprocessingWorker", None' in KFP_STEG.replace("  ", " ").replace("  ", " ") or \
        re.search(r'"PreprocessingWorker",\s*None', KFP_STEG)
    assert re.search(r'"OCRWorker",\s*"preprocess_result"', KFP_STEG)
    assert re.search(r'"NLPWorker",\s*"ocr_result"', KFP_STEG)
    assert re.search(r'"RoutingWorker",\s*"nlp_result"', KFP_STEG)


def test_kfp_steg_bruker_ikke_neste_ko():
    # KFP orkestrerer stegene — ingen rpush til neste kø
    assert "_legg_i_neste_ko" not in KFP_STEG


def test_kfp_steg_sender_feil_til_dlq():
    assert "_send_til_dlq" in KFP_STEG
    assert "raise" in KFP_STEG


def test_kfp_steg_haandterer_ugyldig_overgang():
    # Re-kjøring av fullført steg skal ikke sette jobben til FAILED
    assert "UgyldigTilstandsovergang" in KFP_STEG


# ------------------------------------------------------------------ #
#  API-gating                                                          #
# ------------------------------------------------------------------ #

def test_kjoremodus_standard_er_redis():
    assert 'os.environ.get("KJOREMODUS", "redis")' in LAST_OPP


def test_kubeflow_gren_starter_kfp_kjoring():
    assert 'KJOREMODUS == "kubeflow"' in LAST_OPP
    assert "_start_kfp_kjoring(job_id)" in LAST_OPP


def test_rpush_fortsatt_etter_commit():
    # REL-1-garantien gjelder begge moduser: commit før videresending
    commit_pos = LAST_OPP.index("pg.commit()")
    rpush_pos = LAST_OPP.index("rc.rpush(")
    kfp_pos = LAST_OPP.index("_start_kfp_kjoring(job_id)")
    assert commit_pos < rpush_pos
    assert commit_pos < kfp_pos


# ------------------------------------------------------------------ #
#  config_loader env-overrides                                         #
# ------------------------------------------------------------------ #

def test_sok_url_kan_overstyres():
    assert 'os.environ.get("SOK_URL")' in CONFIG_LOADER


def test_label_studio_url_kan_overstyres():
    assert 'os.environ.get("LABEL_STUDIO_URL")' in CONFIG_LOADER


# ------------------------------------------------------------------ #
#  Pipelines og manifester                                             #
# ------------------------------------------------------------------ #

def test_dokument_pipeline_har_fire_steg_i_rekkefolge():
    for navn in ["preprocess_steg", "ocr_steg", "nlp_steg", "routing_steg"]:
        assert navn in DOKUMENT_PIPELINE
    assert "o.after(p)" in DOKUMENT_PIPELINE
    assert "n.after(o)" in DOKUMENT_PIPELINE
    assert "r.after(n)" in DOKUMENT_PIPELINE


def test_dokument_pipeline_monterer_pvc_og_secret():
    assert "mount_pvc" in DOKUMENT_PIPELINE
    assert "nav-data" in DOKUMENT_PIPELINE
    assert "use_secret_as_env" in DOKUMENT_PIPELINE
    assert "POSTGRES_URL" in DOKUMENT_PIPELINE


def test_kompilerte_pipelines_finnes():
    assert Path("kubeflow/dokument_pipeline.yaml").exists()
    assert Path("kubeflow/trenings_pipeline.yaml").exists()


def test_k8s_manifester_er_gyldig_yaml():
    k8s = Path("k8s")
    filer = sorted(k8s.glob("*.yaml"))
    assert len(filer) >= 12, "forventer minst 12 manifest-filer i k8s/"
    for fil in filer:
        for dok in yaml.safe_load_all(fil.read_text(encoding="utf-8")):
            assert dok is not None, f"tomt dokument i {fil}"


def test_api_deployment_kjorer_hybrid_redis_modus():
    """Hybrid-arkitektur: redis for dokumentflyt, kubeflow kun for trening."""
    api = Path("k8s/10-api.yaml").read_text(encoding="utf-8")
    assert "KJOREMODUS" in api
    assert "value: redis" in api
    assert "KFP_ENDPOINT" in api  # kubeflow-modus fortsatt tilgjengelig


def test_worker_deployments_finnes_for_hybrid():
    import yaml as _yaml
    workers = Path("k8s/13-workers.yaml").read_text(encoding="utf-8")
    navn = [d["metadata"]["name"] for d in _yaml.safe_load_all(workers)]
    assert navn == ["preprocessing-worker", "ocr-worker", "nlp-worker", "routing-worker"]
    assert "kustomization" not in navn
    kust = Path("k8s/kustomization.yaml").read_text(encoding="utf-8")
    assert "13-workers.yaml" in kust


def test_autoskalering_er_valgfri_og_utenfor_kustomization():
    kust = Path("k8s/kustomization.yaml").read_text(encoding="utf-8")
    assert "- 14-autoskalering.yaml" not in kust  # krever KEDA — separat apply
    skalering = Path("k8s/14-autoskalering.yaml").read_text(encoding="utf-8")
    assert "keda.sh" in skalering
    assert "queue:ocr" in skalering


def test_hemmeligheter_brukes_ikke_hardkodet_i_api_deployment():
    api = Path("k8s/10-api.yaml").read_text(encoding="utf-8")
    assert "secretKeyRef" in api


# ------------------------------------------------------------------ #
#  API-image (tidligere manglet psycopg2/pyyaml/config/delt)           #
# ------------------------------------------------------------------ #

def test_api_krav_har_noedvendige_pakker():
    for pakke in ["psycopg2-binary", "pyyaml", "kfp"]:
        assert pakke in API_KRAV, f"{pakke} mangler i api/krav.txt"


def test_api_dockerfile_kopierer_config_og_delt():
    assert "COPY config /app/config" in API_DOCKERFILE
    assert "COPY delt /app/delt" in API_DOCKERFILE
    assert "COPY kubeflow /app/kubeflow" in API_DOCKERFILE
