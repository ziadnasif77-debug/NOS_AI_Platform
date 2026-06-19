import sys
import requests


def sjekk() -> bool:
    try:
        svar = requests.get("http://localhost:8003/helse", timeout=5)
        return svar.status_code == 200
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(0 if sjekk() else 1)
