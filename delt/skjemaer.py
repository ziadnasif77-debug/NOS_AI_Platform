from pydantic import BaseModel, model_validator
from typing import Any, Optional, List
from datetime import datetime


class DokumentInntak(BaseModel):
    fil_id: str
    filnavn: str
    fil_sti: str
    mottatt_tidspunkt: datetime
    antall_sider: int


class SideResultat(BaseModel):
    side_nummer: int
    dokumenttype: str
    raa_tekst: str
    renset_tekst: str
    konfidens: float
    til_gjennomgang: bool


class UttrukketData(BaseModel):
    fil_id: str
    fodselsnummer: Optional[str] = None
    navn: Optional[str] = None
    dato: Optional[str] = None
    adresse: Optional[str] = None
    signatur: Optional[str] = None   # LayoutLMv3
    ytelse: Optional[str] = None
    kontornavn: Optional[str] = None
    fylke: Optional[str] = None
    dokumenttype: str
    utfall: Optional[str] = None
    oppsummering: Optional[str] = None


class SokResultat(BaseModel):
    fil_id: str
    filnavn: str
    side_nummer: int
    utdrag: str
    konfidens: float
    metadata: UttrukketData


# ================================================================== #
#  Worker-kontrakter (inter-worker payload schemas)                    #
#  Versjonert med schema_version for fremtidig kompatibilitet.         #
# ================================================================== #

class PreprocessResultat(BaseModel):
    """Produsert av PreprocessingWorker, konsumert av OCRWorker."""
    schema_version: int = 1
    job_id: str
    document_type: str
    quality_score: float
    quality_approved: bool
    preprocessed_path: str
    rejection_reason: Optional[str] = None


class OCRResultat(BaseModel):
    """Produsert av OCRWorker, konsumert av NLPWorker."""
    schema_version: int = 1
    job_id: str
    text: str
    confidence: float
    tokens: List[Any] = []
    boxes: List[Any] = []
    ocr_model_used: str
    # document_type videreføres fra PreprocessResultat — NLPWorker trenger den for modellvalg
    document_type: str
    raw_path: str
    clean_path: str
    confidence_approved: bool


class ValideringsResultat(BaseModel):
    """Inline valideringsresultat fra NLPWorker."""
    gyldig: bool
    feil: List[str] = []


class AnomalyResultat(BaseModel):
    """Inline anomaly-deteksjon fra NLPWorker."""
    har_anomali: bool
    anomali_score: float
    detaljer: List[str] = []


class NLPResultat(BaseModel):
    """Produsert av NLPWorker, konsumert av RoutingWorker."""
    schema_version: int = 1
    job_id: str
    entities: dict[str, Any]
    document_class: str
    ytelse: Optional[str] = None
    utfall: str
    summary: str
    nlp_confidence: float
    nlp_model_used: str
    validation: ValideringsResultat
    anomaly: AnomalyResultat
    ocr_confidence: float
