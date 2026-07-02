"""
Tester for observabilitet (Prometheus-metrikker) og autentisering
(api_nokkel med konstant-tid-sammenligning + OIDC-modus).
"""
import sys
sys.path.insert(0, ".")
import os
from pathlib import Path

import pytest

HOVED = Path("tjenester/api/hoved.py").read_text(encoding="utf-8")
BASE_WORKER = Path("tjenester/workers/base_worker.py").read_text(encoding="utf-8")
COMPOSE = Path("docker-compose.yml").read_text(encoding="utf-8")
API_KRAV = Path("tjenester/api/krav.txt").read_text(encoding="utf-8")


# ------------------------------------------------------------------ #
#  Autentisering: api_nokkel-modus (ren logikk, ingen avhengigheter)   #
# ------------------------------------------------------------------ #

def test_riktig_nokkel_godtas(monkeypatch):
    monkeypatch.delenv("AUTH_MODUS", raising=False)
    from delt.autentisering import sjekk_forespoersel
    assert sjekk_forespoersel({"X-API-Key": "hemmelig"}, "hemmelig") is None


def test_feil_nokkel_avvises(monkeypatch):
    monkeypatch.delenv("AUTH_MODUS", raising=False)
    from delt.autentisering import sjekk_forespoersel
    assert sjekk_forespoersel({"X-API-Key": "feil"}, "hemmelig") is not None
    assert sjekk_forespoersel({}, "hemmelig") is not None


def test_tom_nokkel_er_aapen_modus(monkeypatch):
    monkeypatch.delenv("AUTH_MODUS", raising=False)
    from delt.autentisering import sjekk_forespoersel
    assert sjekk_forespoersel({}, "") is None


def test_konstant_tid_sammenligning_brukes():
    src = Path("delt/autentisering.py").read_text(encoding="utf-8")
    assert "hmac.compare_digest" in src, "API-nøkkel skal sammenlignes i konstant tid"


def test_oidc_modus_krever_bearer(monkeypatch):
    monkeypatch.setenv("AUTH_MODUS", "oidc")
    from delt.autentisering import sjekk_forespoersel
    assert sjekk_forespoersel({}, "") == "Manglende Bearer-token"
    assert sjekk_forespoersel({"X-API-Key": "nokkel"}, "nokkel") is not None


# ------------------------------------------------------------------ #
#  OIDC: full JWT-validering (krever PyJWT — hoppes over ellers)       #
# ------------------------------------------------------------------ #

def test_oidc_gyldig_og_ugyldig_token(monkeypatch):
    try:
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        privat = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    except BaseException as exc:  # pyo3-panics arver fra BaseException
        pytest.skip(f"PyJWT/cryptography ikke funksjonell: {exc}")
    offentlig = privat.public_key()

    monkeypatch.setenv("AUTH_MODUS", "oidc")
    monkeypatch.setenv("OIDC_ISSUER", "https://utsteder.test")
    monkeypatch.setenv("OIDC_AUDIENCE", "nav-archive")

    import delt.autentisering as auth

    class FalskNokkel:
        key = offentlig

    class FalskJWKKlient:
        def get_signing_key_from_jwt(self, token):
            return FalskNokkel()

    monkeypatch.setattr(auth, "_hent_jwk_klient", lambda: FalskJWKKlient())

    import time as t
    krav = {"iss": "https://utsteder.test", "aud": "nav-archive",
            "sub": "saksbehandler", "exp": int(t.time()) + 300}

    gyldig = jwt.encode(krav, privat, algorithm="RS256")
    assert auth.sjekk_forespoersel({"Authorization": f"Bearer {gyldig}"}, "") is None

    # Feil audience avvises
    feil_aud = jwt.encode(dict(krav, aud="annet-system"), privat, algorithm="RS256")
    assert auth.sjekk_forespoersel({"Authorization": f"Bearer {feil_aud}"}, "") == "Ugyldig token"

    # Utløpt token avvises
    utloept = jwt.encode(dict(krav, exp=int(t.time()) - 10), privat, algorithm="RS256")
    assert auth.sjekk_forespoersel({"Authorization": f"Bearer {utloept}"}, "") == "Ugyldig token"


# ------------------------------------------------------------------ #
#  Metrikker: pen degradering + instrumentering                        #
# ------------------------------------------------------------------ #

def test_metrikker_degraderer_uten_prometheus_client():
    from delt import metrikker
    # Skal aldri kaste — uansett om prometheus_client finnes eller ikke
    metrikker.tell_jobb("queue:test", "ok")
    metrikker.observer_jobb_varighet("queue:test", 1.0)
    metrikker.tell_api("GET", "/helse", 200)
    payload, content_type = metrikker.metrikk_tekst()
    assert isinstance(payload, bytes)
    assert content_type


def test_base_worker_teller_alle_utfall():
    for utfall in ['"ok"', '"retry"', '"dlq"', '"hoppet_over"']:
        assert utfall in BASE_WORKER, f"utfall {utfall} mangler i base_worker"
    assert "start_metrikk_server" in BASE_WORKER


def test_api_har_metrics_endepunkt():
    assert '"/metrics"' in HOVED
    assert "metrikk_middleware" in HOVED
    # /metrics er åpen (Prometheus scraper uten nøkkel), /helse fortsatt åpen
    assert '{"/helse", "/metrics"}' in HOVED


def test_api_bruker_delt_autentisering():
    assert "sjekk_forespoersel" in HOVED
    assert "API_NOKKEL ikke satt" in HOVED  # advarselen skal bestå


# ------------------------------------------------------------------ #
#  Infrastruktur                                                       #
# ------------------------------------------------------------------ #

def test_compose_har_overvaakingsprofil():
    assert "prometheus:" in COMPOSE
    assert "grafana:" in COMPOSE
    assert "overvaaking" in COMPOSE
    assert "METRIKK_PORT=9101" in COMPOSE


def test_api_krav_har_nye_pakker():
    assert "prometheus-client" in API_KRAV
    assert "PyJWT" in API_KRAV


def test_prometheus_scrape_konfig_finnes():
    cfg = Path("overvaaking/prometheus.yml").read_text(encoding="utf-8")
    assert "api:8000" in cfg
    assert "9101" in cfg


def test_k8s_api_har_scrape_annotasjoner():
    api = Path("k8s/10-api.yaml").read_text(encoding="utf-8")
    assert "prometheus.io/scrape" in api
    assert "AUTH_MODUS" in api
