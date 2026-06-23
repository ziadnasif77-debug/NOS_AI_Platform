from pydantic import BaseModel
from typing import Optional, List
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
