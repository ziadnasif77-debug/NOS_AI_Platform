import sys
sys.path.insert(0, ".")
import pytest


# Forventede output-kontrakter for alle workers

PREPROCESS_KEYS = {
    "job_id", "document_type", "quality_score",
    "quality_approved", "preprocessed_path", "rejection_reason",
}

OCR_KEYS = {
    "job_id", "text", "confidence", "tokens", "boxes",
    "ocr_model_used", "raw_path", "clean_path", "confidence_approved",
}

NLP_KEYS = {
    "job_id", "entities", "document_class", "ytelse", "utfall",
    "summary", "nlp_confidence", "nlp_model_used", "validation", "anomaly",
}

ROUTING_KEYS = {
    "job_id", "decision", "label_studio_project", "reason", "audit_trail",
}


def lag_preprocess_resultat(**kwargs):
    base = {
        "job_id": "test-id",
        "document_type": "trykt",
        "quality_score": 0.85,
        "quality_approved": True,
        "preprocessed_path": "/data/test.pdf",
        "rejection_reason": None,
    }
    base.update(kwargs)
    return base


def lag_ocr_resultat(**kwargs):
    base = {
        "job_id": "test-id",
        "text": "Testdokument",
        "confidence": 0.92,
        "tokens": ["Testdokument"],
        "boxes": [],
        "ocr_model_used": "paddleocr",
        "raw_path": "/data/test.pdf",
        "clean_path": "/data/test.pdf",
        "confidence_approved": True,
    }
    base.update(kwargs)
    return base


def test_preprocess_har_alle_nokler():
    res = lag_preprocess_resultat()
    assert PREPROCESS_KEYS.issubset(res.keys())


def test_preprocess_quality_score_range():
    res = lag_preprocess_resultat(quality_score=0.85)
    assert 0.0 <= res["quality_score"] <= 1.0


def test_ocr_har_alle_nokler():
    res = lag_ocr_resultat()
    assert OCR_KEYS.issubset(res.keys())


def test_ocr_confidence_range():
    res = lag_ocr_resultat(confidence=0.92)
    assert 0.0 <= res["confidence"] <= 1.0


def test_routing_beslutning_er_gyldig():
    gyldige = {"APPROVED", "REVIEW", "REJECTED"}
    for beslutning in gyldige:
        res = {
            "job_id": "test",
            "decision": beslutning,
            "label_studio_project": None,
            "reason": "test",
            "audit_trail": [],
        }
        assert res["decision"] in gyldige
