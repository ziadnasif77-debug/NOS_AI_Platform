import yaml
from pathlib import Path

_STI = Path(__file__).parent / "config.yaml"

def last_config() -> dict:
    with open(_STI, encoding="utf-8") as f:
        return yaml.safe_load(f)

CONFIG = last_config()
