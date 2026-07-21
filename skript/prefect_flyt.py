"""
Prefect-flyt for NAV-treningsløkka.

Kjør HELE løkka fra Prefect-UI-et (eller planlagt), og se NØYAKTIG hvilken
milepæl som feilet — med full logg og traceback per steg.

Kjøres i det ISOLERTE .venv-prefect, så Prefect ikke kolliderer med torch/
label-studio i hovedmiljøet. Hver task kaller det tilhørende skriptet i
HOVED-miljøet via subprocess (HOVED_PYTHON, standard «python»), slik at
treningskoden bruker sitt eget miljø med torch.

Oppsett + kjøring (i .venv-prefect):
    prefect server start                          # UI på http://127.0.0.1:4200
    set PREFECT_API_URL=http://127.0.0.1:4200/api
    python skript/prefect_flyt.py                 # kjør løkka én gang
Eller utløs/planlegg fra UI-et.
"""
import os
import subprocess
from pathlib import Path

from prefect import flow, task
from prefect.logging import get_run_logger

ROT = Path(__file__).resolve().parent.parent
# Python i miljøet som har torch/transformers (IKKE Prefect-venv-et).
HOVED_PYTHON = os.environ.get("HOVED_PYTHON", "python")


def _kjor(navn: str, args: list) -> str:
    """Kjør et treningsskript i HOVED-miljøet. Reiser RuntimeError ved
    feil (non-zero exit) med stderr i loggen — så Prefect markerer NØYAKTIG
    hvilket steg som røk, og hvorfor."""
    logger = get_run_logger()
    logger.info("Kjører: %s %s", HOVED_PYTHON, " ".join(args))
    r = subprocess.run([HOVED_PYTHON, *args], cwd=str(ROT),
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.stdout:
        logger.info(r.stdout)
    if r.returncode != 0:
        logger.error(r.stderr or "(ingen stderr)")
        raise RuntimeError(f"{navn} feilet (kode {r.returncode}) — se loggen over")
    return r.stdout


@task(retries=1, retry_delay_seconds=15)
def eksporter() -> str:
    """Steg 1: hent menneskelige korreksjoner fra Label Studio."""
    return _kjor("eksporter", ["skript/eksporter_fra_label_studio.py"])


@task
def finjuster() -> str:
    """Steg 2: tren en norhand-KANDIDAT på korreksjonene (ikke live)."""
    return _kjor("finjuster", ["skript/finjuster.py"])


@task
def kvalitetsport() -> str:
    """Steg 3: valider kandidat mot live (CER) og promoter BARE hvis minst
    like god — ellers står live urørt."""
    return _kjor("kvalitetsport", ["skript/valider_modell.py", "--port"])


@flow(name="nav-treningslop")
def treningslop():
    """Hele treningsløkka som ett sporbart løp: eksporter → finjuster →
    kvalitetsport. Feiler ett steg, ser du det umiddelbart i UI-et med
    loggen og feilen — resten stopper."""
    eksporter()
    finjuster()
    kvalitetsport()


if __name__ == "__main__":
    treningslop()
