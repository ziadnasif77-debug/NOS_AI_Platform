import os
import json
import uuid
import logging
from pathlib import Path


def konfigurer_logging(tjenestenavn: str) -> logging.Logger:
    logger = logging.getLogger(tjenestenavn)
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        f"%(asctime)s [{tjenestenavn}] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def lagre_json(data: dict, sti: str) -> None:
    Path(sti).parent.mkdir(parents=True, exist_ok=True)
    with open(sti, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def les_json(sti: str) -> dict:
    with open(sti, "r", encoding="utf-8") as f:
        return json.load(f)


def generer_fil_id(filnavn: str) -> str:
    stamme = Path(filnavn).stem[:50]
    unik = uuid.uuid4().hex[:8]
    return f"{stamme}_{unik}"
