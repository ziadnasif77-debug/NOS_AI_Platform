"""
PR-5B: Kontraktskompatibilitetstester — verifiserer at producer.model_dump()
er gyldig input for consumer.model_validate() på tvers av alle worker-grenser.

Disse testene fanger opp Schema Drift mellom produserende og konsumerende workers
uten å kreve kjørende tjenester.
"""
import sys
import os
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from delt.skjemaer import (
    PreprocessResultat,
    OCRResultat,
    NLPResultat,
    ValideringsResultat,
    AnomalyResultat,
)
from delt.konstanter import TRYKT, HANDSKRIFT, TABELL


# ------------------------------------------------------------------ #
#  Lag 0 → Lag 1: PreprocessResultat                                  #
# ------------------------------------------------------------------ #

def test_preprocess_roundtrip_godkjent():
    """PreprocessResultat produsert av Lag0 kan konsumeres av Lag1."""
    produsert = PreprocessResultat(
        job_id="abc-123",
        document_type=TRYKT,
        quality_score=0.92,
        quality_approved=True,
        preprocessed_path="/data/behandlet/abc-123.pdf",
        rejection_reason=None,
    ).model_dump()

    konsumert = PreprocessResultat.model_validate(produsert)

    assert konsumert.job_id == "abc-123"
    assert konsumert.document_type == TRYKT
    assert konsumert.quality_approved is True
    assert konsumert.rejection_reason is None
    assert konsumert.schema_version == 1


def test_preprocess_roundtrip_avvist():
    """PreprocessResultat med avvisning bevarer rejection_reason."""
    produsert = PreprocessResultat(
        job_id="xyz-456",
        document_type=HANDSKRIFT,
        quality_score=0.41,
        quality_approved=False,
        preprocessed_path="/data/inntak/xyz-456.pdf",
        rejection_reason="lav_bildekvalitet",
    ).model_dump()

    konsumert = PreprocessResultat.model_validate(produsert)

    assert konsumert.quality_approved is False
    assert konsumert.rejection_reason == "lav_bildekvalitet"


def test_preprocess_manglende_felt_feiler():
    """Payload uten obligatoriske felt skal gi ValidationError."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PreprocessResultat.model_validate({
            "job_id": "abc",
            # mangler document_type, quality_score, quality_approved, preprocessed_path
        })


# ------------------------------------------------------------------ #
#  Lag 1 → Lag 2: OCRResultat                                         #
# ------------------------------------------------------------------ #

def test_ocr_roundtrip_med_tokens():
    """OCRResultat produsert av Lag1 kan konsumeres av Lag2."""
    produsert = OCRResultat(
        job_id="abc-123",
        text="Ola Nordmann søker dagpenger",
        confidence=0.93,
        tokens=["Ola", "Nordmann", "søker", "dagpenger"],
        boxes=[[10, 20, 50, 30], [60, 20, 120, 30]],
        ocr_model_used="paddleocr",
        document_type=TRYKT,
        raw_path="/data/behandlet/abc-123.pdf",
        clean_path="/data/behandlet/abc-123.pdf",
        confidence_approved=True,
    ).model_dump()

    konsumert = OCRResultat.model_validate(produsert)

    assert konsumert.text == "Ola Nordmann søker dagpenger"
    assert konsumert.document_type == TRYKT
    assert konsumert.tokens == ["Ola", "Nordmann", "søker", "dagpenger"]
    assert konsumert.confidence_approved is True


def test_ocr_roundtrip_uten_tokens():
    """OCRResultat med tomme tokens (f.eks. TrOCR) er gyldig."""
    produsert = OCRResultat(
        job_id="abc-124",
        text="Håndskrevet tekst",
        confidence=0.88,
        tokens=[],
        boxes=[],
        ocr_model_used="trocr",
        document_type=HANDSKRIFT,
        raw_path="/data/behandlet/abc-124.pdf",
        clean_path="/data/behandlet/abc-124.pdf",
        confidence_approved=True,
    ).model_dump()

    konsumert = OCRResultat.model_validate(produsert)

    assert konsumert.tokens == []
    assert konsumert.document_type == HANDSKRIFT


def test_ocr_mangler_document_type_feiler():
    """document_type er obligatorisk — uten det feiler validering."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OCRResultat.model_validate({
            "job_id": "abc",
            "text": "tekst",
            "confidence": 0.9,
            "ocr_model_used": "paddleocr",
            # mangler document_type
            "raw_path": "/tmp/x",
            "clean_path": "/tmp/x",
            "confidence_approved": True,
        })


# ------------------------------------------------------------------ #
#  Lag 2 → Lag 3: NLPResultat                                         #
# ------------------------------------------------------------------ #

def test_nlp_roundtrip_godkjent():
    """NLPResultat produsert av Lag2 kan konsumeres av Lag3."""
    validering = ValideringsResultat(gyldig=True, feil=[])
    anomali = AnomalyResultat(har_anomali=False, anomali_score=0.0, detaljer=[])

    produsert = NLPResultat(
        job_id="abc-123",
        entities={"navn": "Ola Nordmann", "fodselsnummer": "01010112345"},
        document_class="skjema",
        ytelse="dagpenger",
        utfall="innvilget",
        summary="Skjema for Ola Nordmann — utfall: innvilget",
        nlp_confidence=0.91,
        nlp_model_used="layoutlmv3",
        validation=validering,
        anomaly=anomali,
        ocr_confidence=0.93,
    ).model_dump()

    konsumert = NLPResultat.model_validate(produsert)

    assert konsumert.nlp_confidence == 0.91
    assert konsumert.validation.gyldig is True
    assert konsumert.anomaly.har_anomali is False
    assert konsumert.entities["navn"] == "Ola Nordmann"


def test_nlp_roundtrip_med_feil():
    """NLPResultat med valideringsfeil bevarer feil-listen."""
    validering = ValideringsResultat(gyldig=False, feil=["ugyldig_fodselsnummer"])
    anomali = AnomalyResultat(har_anomali=True, anomali_score=0.75, detaljer=["ugyldig_fodselsnummer"])

    produsert = NLPResultat(
        job_id="abc-125",
        entities={"navn": "Kari Hansen"},
        document_class="brev",
        ytelse=None,
        utfall="ukjent",
        summary="Brev for Kari Hansen — utfall: ukjent",
        nlp_confidence=0.72,
        nlp_model_used="nb-bert-ner",
        validation=validering,
        anomaly=anomali,
        ocr_confidence=0.88,
    ).model_dump()

    konsumert = NLPResultat.model_validate(produsert)

    assert konsumert.validation.gyldig is False
    assert "ugyldig_fodselsnummer" in konsumert.validation.feil
    assert konsumert.anomaly.har_anomali is True


def test_nlp_manglende_confidence_feiler():
    """nlp_confidence er obligatorisk — silent default 1.0 er ikke lenger mulig."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        NLPResultat.model_validate({
            "job_id": "abc",
            "entities": {},
            "document_class": "ukjent",
            "utfall": "ukjent",
            "summary": "",
            # mangler nlp_confidence — ingen silent default
            "nlp_model_used": "nb-bert",
            "validation": {"gyldig": True, "feil": []},
            "anomaly": {"har_anomali": False, "anomali_score": 0.0, "detaljer": []},
            "ocr_confidence": 0.9,
        })


# ------------------------------------------------------------------ #
#  Schema versjon                                                       #
# ------------------------------------------------------------------ #

def test_alle_kontrakter_har_schema_version_1():
    """Alle worker-kontrakter skal ha schema_version=1."""
    p = PreprocessResultat(
        job_id="x", document_type=TRYKT, quality_score=0.9,
        quality_approved=True, preprocessed_path="/tmp/x"
    )
    o = OCRResultat(
        job_id="x", text="", confidence=0.9, ocr_model_used="p",
        document_type=TRYKT, raw_path="/tmp/x", clean_path="/tmp/x",
        confidence_approved=True
    )
    n = NLPResultat(
        job_id="x", entities={}, document_class="ukjent", utfall="ukjent",
        summary="", nlp_confidence=0.8, nlp_model_used="nb-bert",
        validation=ValideringsResultat(gyldig=True),
        anomaly=AnomalyResultat(har_anomali=False, anomali_score=0.0),
        ocr_confidence=0.9
    )
    assert p.schema_version == 1
    assert o.schema_version == 1
    assert n.schema_version == 1
