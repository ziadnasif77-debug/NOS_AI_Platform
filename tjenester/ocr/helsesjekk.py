import sys
import subprocess


def sjekk() -> bool:
    try:
        resultat = subprocess.run(
            ["htrflow", "--help"],
            capture_output=True,
            timeout=10
        )
        return resultat.returncode == 0
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(0 if sjekk() else 1)
