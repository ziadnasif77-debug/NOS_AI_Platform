"""
Prometheus-metrikker for API og workers.

Degraderer pent: mangler prometheus_client-biblioteket blir alle
funksjoner no-op, slik at tjenestene aldri feiler på grunn av metrikker.

Miljøvariabler:
  METRIKK_PORT — settes i workers for å eksponere /metrics på egen port.
                 API-et eksponerer /metrics på hovedporten i stedet.
"""
import os
import logging

logger = logging.getLogger(__name__)

try:
    from prometheus_client import (
        Counter, Histogram, start_http_server,
        generate_latest, CONTENT_TYPE_LATEST,
    )
    TILGJENGELIG = True
except ImportError:
    TILGJENGELIG = False

if TILGJENGELIG:
    JOBBER_BEHANDLET = Counter(
        "nav_jobber_behandlet_total",
        "Antall jobber behandlet per worker og utfall",
        ["worker", "utfall"],
    )
    JOBB_VARIGHET = Histogram(
        "nav_jobb_varighet_sekunder",
        "Prosesseringstid per jobb",
        ["worker"],
        buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120),
    )
    API_FORESPOERSLER = Counter(
        "nav_api_forespoersler_total",
        "Antall API-forespørsler per rute og status",
        ["metode", "rute", "status"],
    )
    API_LATENS = Histogram(
        "nav_api_latens_sekunder",
        "API-latens per rute",
        ["rute"],
        buckets=(0.01, 0.05, 0.1, 0.2, 0.5, 1, 2, 5),
    )


def tell_jobb(worker: str, utfall: str):
    if TILGJENGELIG:
        JOBBER_BEHANDLET.labels(worker=worker, utfall=utfall).inc()


def observer_jobb_varighet(worker: str, sekunder: float):
    if TILGJENGELIG:
        JOBB_VARIGHET.labels(worker=worker).observe(sekunder)


def tell_api(metode: str, rute: str, status: int):
    if TILGJENGELIG:
        API_FORESPOERSLER.labels(metode=metode, rute=rute, status=str(status)).inc()


def observer_api_latens(rute: str, sekunder: float):
    if TILGJENGELIG:
        API_LATENS.labels(rute=rute).observe(sekunder)


def start_metrikk_server():
    """Starter HTTP-server for /metrics i workers (hvis METRIKK_PORT er satt)."""
    port = os.environ.get("METRIKK_PORT")
    if not port:
        return
    if not TILGJENGELIG:
        logger.warning("METRIKK_PORT satt, men prometheus_client mangler — ingen metrikker.")
        return
    start_http_server(int(port))
    logger.info("Metrikk-server lytter på port %s", port)


def metrikk_tekst():
    """Returnerer (payload, content_type) for /metrics-endepunktet."""
    if not TILGJENGELIG:
        return b"# prometheus_client ikke installert\n", "text/plain"
    return generate_latest(), CONTENT_TYPE_LATEST
