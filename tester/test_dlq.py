import sys
sys.path.insert(0, ".")
import pytest

BACKOFF = [1, 3, 10]
MAX_RETRIES = 3


def bestem_backoff(retry_count: int) -> int:
    return BACKOFF[min(retry_count, len(BACKOFF) - 1)]


def haandter_feil(job: dict, feil: str, send_til_dlq_fn):
    retry_count = job.get("retry_count", 0)
    if retry_count < MAX_RETRIES:
        job["retry_count"] = retry_count + 1
        backoff = bestem_backoff(retry_count)
        return "retry", backoff
    else:
        send_til_dlq_fn(job, feil)
        return "dlq", 0


def test_foerste_feil_gir_retry():
    jobb = {"job_id": "abc", "retry_count": 0}
    dlq_kalt = []
    aksjon, backoff = haandter_feil(jobb, "timeout", dlq_kalt.append)
    assert aksjon == "retry"
    assert backoff == BACKOFF[0]
    assert jobb["retry_count"] == 1
    assert len(dlq_kalt) == 0


def test_backoff_sekvens():
    for i, forventet in enumerate(BACKOFF):
        assert bestem_backoff(i) == forventet


def test_etter_maks_retries_gaar_til_dlq():
    jobb = {"job_id": "abc", "retry_count": MAX_RETRIES}
    dlq_mottatt = []
    aksjon, _ = haandter_feil(jobb, "timeout", lambda j, e: dlq_mottatt.append(j))
    assert aksjon == "dlq"
    assert len(dlq_mottatt) == 1
    assert dlq_mottatt[0]["job_id"] == "abc"


def test_retry_count_oeker_for_hver_feil():
    jobb = {"job_id": "abc", "retry_count": 0}
    for forventet_count in range(1, MAX_RETRIES + 1):
        if jobb["retry_count"] < MAX_RETRIES:
            haandter_feil(jobb, "feil", lambda j, e: None)
            assert jobb["retry_count"] == forventet_count
