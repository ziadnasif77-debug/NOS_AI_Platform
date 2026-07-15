"""
SEC-1A: API-nøkkel beskytter sensitive endepunkter (source-level verification)
SEC-1B: FNR ikke i Milvus-skjema eller søkerespons
SEC-1C: Filter-whitelist forhindrer injeksjon
REL-1:  pg.commit() skjer FØR rc.rpush() i /last-opp/
OBS-1:  Audit-feil loggføres som ERROR, ikke svelget stille
"""
import sys
import os
import re
import json
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _les(relativ_sti: str) -> str:
    return open(os.path.join(ROOT, relativ_sti)).read()


# ------------------------------------------------------------------ #
#  SEC-1A — API-nøkkel middleware                                     #
# ------------------------------------------------------------------ #

def test_aapne_stier_inneholder_kun_helse():
    """Kun /helse skal være åpent — /resultat, /audit, /jobb er beskyttede."""
    src = _les("tjenester/api/hoved.py")
    # AAPNE_STIER skal kun inneholde /helse
    assert '"/helse"' in src
    # /resultat, /audit, /jobb skal ikke stå i åpne stier-settet
    assert '"/resultat/"' not in src
    assert '"/audit/"' not in src
    assert '"/jobb/"' not in src


def test_api_hoved_gir_advarsel_uten_api_nokkel():
    """Manglende API_NOKKEL skal logge advarsel (kode-verifisering)."""
    src = _les("tjenester/api/hoved.py")
    assert "API_NOKKEL ikke satt" in src
    assert "logger.warning" in src


def test_sok_tjeneste_har_api_nokkel_middleware():
    """Soketjenesten skal ha sin egen X-API-Key middleware."""
    src = _les("tjenester/sok/hoved.py")
    assert "X-API-Key" in src
    assert "api_nokkel_middleware" in src
    assert "401" in src


def test_sok_tjeneste_gir_advarsel_uten_api_nokkel():
    """Soketjenestens manglende API_NOKKEL skal logge advarsel."""
    src = _les("tjenester/sok/hoved.py")
    assert "API_NOKKEL ikke satt" in src


def test_helse_er_eneste_aapne_sti_i_sok():
    """Soketjenesten: kun /helse er åpent."""
    src = _les("tjenester/sok/hoved.py")
    # /metrics er åpen for Prometheus-scraping — bevisst unntak
    assert 'AAPNE_STIER_SOK = {"/helse", "/metrics"}' in src


# ------------------------------------------------------------------ #
#  SEC-1B — FNR ikke i Milvus                                         #
# ------------------------------------------------------------------ #

def test_milvus_skjema_inneholder_ikke_fodselsnummer():
    """_opprett_samling skal ikke definere et fodselsnummer-felt."""
    src = _les("tjenester/sok/hoved.py")
    assert 'FieldSchema("fodselsnummer"' not in src, \
        "fodselsnummer skal ikke lagres i Milvus-skjemaet"


def test_indekser_payload_inneholder_ikke_fodselsnummer():
    """_send_til_milvus i RoutingWorker skal ikke sende fodselsnummer."""
    src = _les("tjenester/workers/lag3_routing/lag3.py")
    # fodselsnummer skal ikke sendes i Milvus-payload
    assert '"fodselsnummer": entiteter.get' not in src, \
        "fodselsnummer skal ikke inngå i Milvus-payload"


def test_sok_output_fields_mangler_fodselsnummer():
    """Søke-endepunktet skal ikke hente fodselsnummer fra Milvus."""
    src = _les("tjenester/sok/hoved.py")
    treffer = re.search(r'output_fields\s*=\s*\[([^\]]+)\]', src)
    assert treffer, "output_fields ikke funnet i sok/hoved.py"
    assert "fodselsnummer" not in treffer.group(1), \
        "fodselsnummer skal ikke returneres fra Milvus-søk"


def test_indekser_insert_mangler_fodselsnummer():
    """/indekser-endepunktet skal ikke sette inn fodselsnummer i Milvus."""
    src = _les("tjenester/sok/hoved.py")
    indekser_blokk = src[src.find("@app.post(\"/indekser\")"):]
    indekser_blokk = indekser_blokk[:indekser_blokk.find("@app.post(", 10)]
    assert '"fodselsnummer"' not in indekser_blokk, \
        "fodselsnummer skal ikke settes inn i Milvus via /indekser"


# ------------------------------------------------------------------ #
#  SEC-1C — Filter-whitelist                                          #
# ------------------------------------------------------------------ #

def test_lovlige_ytelser_whitelist_finnes():
    """LOVLIGE_YTELSER skal finnes og peke på den kanoniske listen."""
    src = _les("tjenester/sok/hoved.py")
    assert "LOVLIGE_YTELSER" in src
    from delt.konstanter import NORSKE_YTELSER
    assert "dagpenger" in NORSKE_YTELSER
    assert "sykepenger" in NORSKE_YTELSER


def test_lovlige_fylker_whitelist_finnes():
    """LOVLIGE_FYLKER skal finnes og peke på den kanoniske listen."""
    src = _les("tjenester/sok/hoved.py")
    assert "LOVLIGE_FYLKER" in src
    from delt.konstanter import NORSKE_FYLKER
    assert "Oslo" in NORSKE_FYLKER


def test_bygg_filter_validerer_ytelse():
    """_bygg_filter skal avvise ugyldig ytelse."""
    src = _les("tjenester/sok/hoved.py")
    assert "ytelse not in LOVLIGE_YTELSER" in src
    assert "status_code=400" in src


def test_bygg_filter_validerer_fylke():
    """_bygg_filter skal avvise ugyldig fylke."""
    src = _les("tjenester/sok/hoved.py")
    assert "fylke not in LOVLIGE_FYLKER" in src


def test_fodselsnummer_ikke_lenger_filter():
    """fodselsnummer-filter er fjernet fra _bygg_filter."""
    src = _les("tjenester/sok/hoved.py")
    filter_funk = src[src.find("def _bygg_filter"):]
    filter_funk = filter_funk[:filter_funk.find("\ndef ")]
    assert "fodselsnummer" not in filter_funk, \
        "fodselsnummer-filter skal ikke finnes — feltet er fjernet fra Milvus"


def test_bygg_filter_validerer_fil_id():
    """fil_id-filter skal valideres for å unngå injeksjon."""
    src = _les("tjenester/sok/hoved.py")
    filter_funk = src[src.find("def _bygg_filter"):]
    filter_funk = filter_funk[:filter_funk.find("\ndef ")]
    assert "isalnum" in filter_funk, \
        "fil_id skal valideres med isalnum() for å hindre injeksjon"


# ------------------------------------------------------------------ #
#  REL-1 — commit før rpush i /last-opp/                             #
# ------------------------------------------------------------------ #

def test_pg_commit_foer_rpush_i_last_opp():
    """pg.commit() skal skje FØR rc.rpush() — aldri omvendt."""
    src = _les("tjenester/api/ruter/last_opp.py")
    commit_pos = src.find("pg.commit()")
    rpush_pos = src.find("rc.rpush(")
    assert commit_pos != -1, "pg.commit() ikke funnet i last_opp.py"
    assert rpush_pos != -1, "rc.rpush() ikke funnet i last_opp.py"
    assert commit_pos < rpush_pos, (
        f"pg.commit() (pos {commit_pos}) skal komme FØR rc.rpush() (pos {rpush_pos})"
    )


def test_ingen_rpush_foer_commit():
    """rc.rpush()-kallet skal ikke forekomme mellom INSERT og pg.commit()."""
    src = _les("tjenester/api/ruter/last_opp.py")
    insert_pos = src.find("INSERT INTO jobs")
    commit_pos = src.find("pg.commit()")
    mellom = src[insert_pos:commit_pos]
    assert "rc.rpush(" not in mellom, \
        "rc.rpush() skal ikke kalles mellom INSERT og pg.commit()"


# ------------------------------------------------------------------ #
#  OBS-1 — Audit-feil ikke svelget                                   #
# ------------------------------------------------------------------ #

def test_audit_feil_logges_ikke_som_bare_pass():
    """Audit-skriving som feiler skal ikke svelges med 'pass' alene."""
    src = _les("tjenester/workers/base_worker.py")
    # Finn _audit-funksjonen
    audit_start = src.find("def _audit(")
    audit_src = src[audit_start:]
    # 'except Exception:\n                pass' skal ikke finnes
    assert "except Exception:\n                pass" not in audit_src, \
        "Audit-feil skal ikke svelges med bare 'pass'"


def test_audit_feil_bruker_logger_error():
    """Audit-feil skal logge med logger.error og AUDIT_FEIL-nøkkelord."""
    src = _les("tjenester/workers/base_worker.py")
    assert "AUDIT_FEIL" in src, \
        "Audit-feil skal logges med AUDIT_FEIL-nøkkelord for enkel filtrering"
    audit_start = src.find("def _audit(")
    audit_src = src[audit_start:]
    error_blokk = audit_src[:audit_src.find("\n    def ", 10) if "\n    def " in audit_src else len(audit_src)]
    assert "logger.error" in error_blokk, \
        "logger.error skal brukes i _audit ved feil"
