import os
import logging
import yaml
from pathlib import Path

_STI = Path(__file__).parent / "config.yaml"
logger = logging.getLogger(__name__)


def last_config() -> dict:
    konfig = yaml.safe_load(open(_STI, encoding="utf-8"))

    # Env vars overstyrer config.yaml — nødvendig for produksjon.
    # Sett POSTGRES_URL og REDIS_URL i miljøet (K8s Secret, .env, osv.)
    postgres_url = os.environ.get("POSTGRES_URL")
    if postgres_url:
        konfig["postgres"]["url"] = postgres_url
    else:
        if "nav:nav@" in konfig["postgres"].get("url", ""):
            logger.warning(
                "POSTGRES_URL ikke satt — bruker standard-passord fra config.yaml. "
                "Sett POSTGRES_URL i produksjonsmiljøet."
            )

    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        konfig["redis"]["url"] = redis_url

    return konfig


CONFIG = last_config()
