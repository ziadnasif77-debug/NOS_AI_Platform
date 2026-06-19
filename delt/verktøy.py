import os
import json
import logging
from datetime import datetime
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
    tidsstempel = datetime.now().strftime("%Y%m%d_%H%M%S")
    stamme = Path(filnavn).stem
    return f"{stamme}_{tidsstempel}"
