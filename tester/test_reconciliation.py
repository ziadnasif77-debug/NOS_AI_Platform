import sys
sys.path.insert(0, ".")
import pytest
from datetime import datetime, timedelta

LOCK_TIMEOUT_SEK = 60
GHOST_TIMEOUT_MIN = 10


def finn_stuck_jobber(jobber: list) -> list:
    """Jobber med lås som har utløpt."""
    return [
        j for j in jobber
        if j.get("locked_by") and j.get("lock_expiry")
        and j["lock_expiry"] < datetime.utcnow()
        and j["state"] not in ("DONE", "FAILED")
    ]


def finn_ghost_states(jobber: list) -> list:
    """Aktive jobber uten lås som ikke er oppdatert på over 10 min."""
    grense = datetime.utcnow() - timedelta(minutes=GHOST_TIMEOUT_MIN)
    return [
        j for j in jobber
        if j["state"] not in ("DONE", "FAILED", "UPLOADED")
        and not j.get("locked_by")
        and j.get("oppdatert", datetime.utcnow()) < grense
    ]


def finn_tapte_jobber(jobber: list) -> list:
    """UPLOADED jobber som ikke har blitt QUEUED på over 5 min."""
    grense = datetime.utcnow() - timedelta(minutes=5)
    return [
        j for j in jobber
        if j["state"] == "UPLOADED"
        and j.get("opprettet", datetime.utcnow()) < grense
    ]


def test_ingen_stuck_uten_utlopte_laaser():
    jobber = [
        {"job_id": "1", "state": "PREPROCESSING", "locked_by": "w1",
         "lock_expiry": datetime.utcnow() + timedelta(seconds=30)}
    ]
    assert finn_stuck_jobber(jobber) == []


def test_stuck_jobb_identifiseres():
    jobber = [
        {"job_id": "1", "state": "OCR_PROCESSING", "locked_by": "w1",
         "lock_expiry": datetime.utcnow() - timedelta(seconds=10)}
    ]
    stuck = finn_stuck_jobber(jobber)
    assert len(stuck) == 1
    assert stuck[0]["job_id"] == "1"


def test_terminal_stuck_ignoreres():
    jobber = [
        {"job_id": "1", "state": "DONE", "locked_by": "w1",
         "lock_expiry": datetime.utcnow() - timedelta(seconds=100)},
        {"job_id": "2", "state": "FAILED", "locked_by": "w2",
         "lock_expiry": datetime.utcnow() - timedelta(seconds=100)},
    ]
    assert finn_stuck_jobber(jobber) == []


def test_ghost_state_identifiseres():
    gammel = datetime.utcnow() - timedelta(minutes=15)
    jobber = [
        {"job_id": "1", "state": "NLP_PROCESSING", "locked_by": None, "oppdatert": gammel}
    ]
    ghost = finn_ghost_states(jobber)
    assert len(ghost) == 1


def test_nylig_oppdatert_er_ikke_ghost():
    ny = datetime.utcnow() - timedelta(minutes=2)
    jobber = [
        {"job_id": "1", "state": "NLP_PROCESSING", "locked_by": None, "oppdatert": ny}
    ]
    assert finn_ghost_states(jobber) == []


def test_tapt_jobb_identifiseres():
    gammel = datetime.utcnow() - timedelta(minutes=10)
    jobber = [{"job_id": "1", "state": "UPLOADED", "opprettet": gammel}]
    tapte = finn_tapte_jobber(jobber)
    assert len(tapte) == 1


def test_ny_uploaded_er_ikke_tapt():
    ny = datetime.utcnow() - timedelta(minutes=1)
    jobber = [{"job_id": "1", "state": "UPLOADED", "opprettet": ny}]
    assert finn_tapte_jobber(jobber) == []
