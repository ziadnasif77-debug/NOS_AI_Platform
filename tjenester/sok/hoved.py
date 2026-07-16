import os
import sys
import time
import threading
import torch
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from rank_bm25 import BM25Okapi
import numpy as np

sys.path.insert(0, "/app")
from delt.verktøy import konfigurer_logging
from delt.autentisering import sjekk_forespoersel
from delt import metrikker
try:
    from fusjon import rrf_fusjoner          # container: /app/fusjon.py
except ImportError:
    from tjenester.sok.fusjon import rrf_fusjoner  # repo-kjøring/tester

logger = konfigurer_logging("sok-tjeneste")

API_NOKKEL = os.environ.get("API_NOKKEL", "")
if not API_NOKKEL:
    logger.warning(
        "API_NOKKEL ikke satt — soketjenesten er ubeskyttet. "
        "Sett miljøvariabelen API_NOKKEL i produksjon."
    )

AAPNE_STIER_SOK = {"/helse", "/metrics"}

MODELLER_STI = os.environ.get("MODELLER_STI", "/modeller")
MILVUS_VERT = os.environ.get("MILVUS_VERT", "milvus")
MILVUS_PORT = int(os.environ.get("MILVUS_PORT", "19530"))
MILVUS_SAMLING = os.environ.get("MILVUS_SAMLING", "nav_dokumenter")
MILVUS_RETRY_SEKUNDER = int(os.environ.get("MILVUS_RETRY_SEKUNDER", "60"))

# ------------------------------------------------------------------ #
#  Global tilstand                                                      #
# ------------------------------------------------------------------ #

_milvus_tilgjengelig = False
_samling = None
_embedding_modell = None
_embedding_tilgjengelig = False

# BM25 holdes i minnet med lazy rebuild: innsetting markerer indeksen
# som skitten, og den gjenoppbygges først ved neste søk. Dette fjerner
# O(N)-rebuild per dokument. Ved millionvolum skal BM25 flyttes til
# Milvus sparse-vektorer — se docs/HYBRID_ARKITEKTUR.md.
_bm25_dokumenter: list = []       # [{"fil_id": ..., "tekst": ...}]
bm25_indeks = None
_bm25_skitten = False
_bm25_lås = threading.Lock()


# ------------------------------------------------------------------ #
#  Startup-logikk                                                       #
# ------------------------------------------------------------------ #

def _koble_til_milvus() -> bool:
    """Forsøker å koble til Milvus i maks MILVUS_RETRY_SEKUNDER sekunder."""
    from pymilvus import connections, MilvusException
    forsinkelse = 2
    slutt = time.monotonic() + MILVUS_RETRY_SEKUNDER
    forsok = 0
    while time.monotonic() < slutt:
        forsok += 1
        try:
            connections.connect(host=MILVUS_VERT, port=MILVUS_PORT, timeout=5)
            logger.info("Milvus tilkoblet (forsøk %d).", forsok)
            return True
        except Exception as exc:
            gjenstår = max(0, slutt - time.monotonic())
            logger.warning(
                "Milvus forsøk %d feilet: %s — %ds igjen.", forsok, exc, int(gjenstår)
            )
            if time.monotonic() + forsinkelse > slutt:
                break
            time.sleep(forsinkelse)
            forsinkelse = min(forsinkelse * 2, 15)
    logger.error("Milvus ikke tilgjengelig etter %ds — starter i degradert modus.", MILVUS_RETRY_SEKUNDER)
    return False


def _opprett_samling():
    from pymilvus import Collection, CollectionSchema, FieldSchema, DataType, utility
    if utility.has_collection(MILVUS_SAMLING):
        return Collection(MILVUS_SAMLING)
    felt = [
        FieldSchema("id",           DataType.INT64,        is_primary=True, auto_id=True),
        FieldSchema("fil_id",       DataType.VARCHAR,       max_length=200),
        FieldSchema("filnavn",      DataType.VARCHAR,       max_length=500),
        FieldSchema("side_nummer",  DataType.INT64),
        FieldSchema("tekst",        DataType.VARCHAR,       max_length=65535),
        FieldSchema("navn",         DataType.VARCHAR,       max_length=200),
        FieldSchema("dato",         DataType.VARCHAR,       max_length=50),
        FieldSchema("ytelse",       DataType.VARCHAR,       max_length=100),
        FieldSchema("fylke",        DataType.VARCHAR,       max_length=100),
        FieldSchema("dokumenttype", DataType.VARCHAR,       max_length=100),
        FieldSchema("vektor",       DataType.FLOAT_VECTOR,  dim=1024),
    ]
    skjema = CollectionSchema(felt, "NAV historiske dokumenter")
    samling = Collection(MILVUS_SAMLING, skjema)
    samling.create_index(
        "vektor",
        {"index_type": "HNSW", "metric_type": "COSINE", "params": {"M": 16, "efConstruction": 200}},
    )
    return samling


def _last_embedding_modell():
    from sentence_transformers import SentenceTransformer
    enhet = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("Laster Qwen3-Embedding på %s ...", enhet)
    modell = SentenceTransformer(f"{MODELLER_STI}/qwen3-embed", device=enhet)
    logger.info("Embedding-modell klar.")
    return modell


def _gjenoppbygg_bm25(samling) -> None:
    global bm25_indeks, _bm25_dokumenter, _bm25_skitten
    try:
        samling.load()
        hentet = []
        grense, offset = 1000, 0
        while True:
            batch = samling.query(
                expr='fil_id != ""',
                output_fields=["fil_id", "side_nummer", "tekst"],
                limit=grense,
                offset=offset,
            )
            if not batch:
                break
            hentet.extend(batch)
            offset += len(batch)
            if len(batch) < grense:
                break
        with _bm25_lås:
            _bm25_dokumenter = [
                {"fil_id": d["fil_id"], "side_nummer": d.get("side_nummer", 0),
                 "tekst": d["tekst"]} for d in hentet
            ]
            if _bm25_dokumenter:
                bm25_indeks = BM25Okapi([d["tekst"].split() for d in _bm25_dokumenter])
            _bm25_skitten = False
        logger.info("BM25 gjenoppbygd: %d dokumenter.", len(_bm25_dokumenter))
    except Exception as feil:
        logger.warning("BM25-gjenoppbygging feilet (fortsetter med tom indeks): %s", feil)


# ------------------------------------------------------------------ #
#  Lifespan                                                             #
# ------------------------------------------------------------------ #

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _milvus_tilgjengelig, _samling, _embedding_modell, _embedding_tilgjengelig

    # 1. Last embedding-modell — kritisk; avslutt hvis den feiler
    try:
        _embedding_modell = _last_embedding_modell()
        _embedding_tilgjengelig = True
    except Exception as exc:
        logger.critical("Embedding-modell (Qwen3) kunne ikke lastes: %s", exc)
        logger.critical("Soketjenesten kan ikke fungere uten embedding-modell — avslutter.")
        sys.exit(1)

    # 2. Koble til Milvus med retry — degradert modus hvis det feiler
    _milvus_tilgjengelig = _koble_til_milvus()
    if _milvus_tilgjengelig:
        try:
            _samling = _opprett_samling()
            _gjenoppbygg_bm25(_samling)
        except Exception as exc:
            logger.error("Milvus-samling kunne ikke opprettes/lastes: %s — degradert modus.", exc)
            _milvus_tilgjengelig = False

    yield
    # Teardown (ingenting å rydde for nå)


app = FastAPI(title="NAV Soketjeneste", lifespan=lifespan)


@app.middleware("http")
async def api_nokkel_middleware(forespørsel: Request, neste):
    """
    Krev X-API-Key header på alle endepunkter unntatt /helse og /metrics.
    Bruker delt.autentisering (konstant-tid-sammenligning, OIDC-støtte).
    """
    sti = forespørsel.url.path
    if sti not in AAPNE_STIER_SOK:
        feil = sjekk_forespoersel(forespørsel.headers, API_NOKKEL)
        if feil:
            return JSONResponse({"feil": feil}, status_code=401)
    return await neste(forespørsel)


@app.get("/metrics")
async def metrics():
    from fastapi.responses import Response
    payload, content_type = metrikker.metrikk_tekst()
    return Response(content=payload, media_type=content_type)


# ------------------------------------------------------------------ #
#  Hjelpefunksjon: sjekk Milvus                                        #
# ------------------------------------------------------------------ #

def _krev_milvus():
    if not _milvus_tilgjengelig or _samling is None:
        raise HTTPException(
            status_code=503,
            detail={"status": "feil", "grunn": "milvus_utilgjengelig"},
        )


# ------------------------------------------------------------------ #
#  Endepunkter                                                          #
# ------------------------------------------------------------------ #

@app.post("/indekser")
async def indekser(data: dict):
    _krev_milvus()
    global bm25_indeks, _bm25_dokumenter, _bm25_skitten
    tekst = data.get("tekst", "")
    metadata = data.get("metadata", {})
    fil_id = metadata.get("fil_id", "")
    side_nummer = int(metadata.get("side_nummer", 0) or 0)
    if not fil_id or not fil_id.replace("-", "").isalnum() or len(fil_id) > 200:
        raise HTTPException(status_code=400, detail="Ugyldig fil_id")
    try:
        vektor = _embedding_modell.encode(tekst[:2048], normalize_embeddings=True).tolist()
        # Idempotent indeksering PER SIDE: (fil_id, side_nummer) er nøkkelen —
        # retries skal ikke gi duplikater, og side 2 skal ikke slette side 1.
        _samling.delete(f'fil_id == "{fil_id}" && side_nummer == {side_nummer}')
        _samling.insert([{
            "fil_id":       metadata.get("fil_id", ""),
            "filnavn":      data.get("filnavn", ""),
            "side_nummer":  side_nummer,
            "tekst":        tekst[:65000],
            "navn":         metadata.get("navn") or "",
            "dato":         metadata.get("dato") or "",
            "ytelse":       metadata.get("ytelse") or "",
            "fylke":        metadata.get("fylke") or "",
            "dokumenttype": metadata.get("dokumenttype") or "",
            "vektor":       vektor,
        }])
        with _bm25_lås:
            _bm25_dokumenter = [
                d for d in _bm25_dokumenter
                if not (d["fil_id"] == fil_id and d.get("side_nummer", 0) == side_nummer)
            ]
            _bm25_dokumenter.append(
                {"fil_id": fil_id, "side_nummer": side_nummer, "tekst": tekst}
            )
            _bm25_skitten = True   # lazy rebuild ved neste søk — ikke O(N) per insert
        _samling.flush()
        return {"status": "indeksert", "fil_id": fil_id}
    except HTTPException:
        raise
    except Exception as feil:
        logger.error("Indekseringsfeil: %s", feil)
        raise HTTPException(status_code=500, detail=str(feil))


@app.delete("/dokument/{fil_id}")
async def slett_dokument(fil_id: str):
    """Oppbevaring/GDPR: fjern ALLE sider for et dokument fra indeksen.
    Kalles av oppbevaringsjobben når dokumentet passerer maks alder."""
    _krev_milvus()
    global _bm25_dokumenter, _bm25_skitten
    if not fil_id or not fil_id.replace("-", "").isalnum() or len(fil_id) > 200:
        raise HTTPException(status_code=400, detail="Ugyldig fil_id")
    try:
        _samling.delete(f'fil_id == "{fil_id}"')
        _samling.flush()
        with _bm25_lås:
            _bm25_dokumenter = [d for d in _bm25_dokumenter if d["fil_id"] != fil_id]
            _bm25_skitten = True
        return {"status": "slettet", "fil_id": fil_id}
    except Exception as feil:
        logger.error("Slettefeil for %s: %s", fil_id, feil)
        raise HTTPException(status_code=500, detail=str(feil))


@app.post("/sok")
async def sok(data: dict):
    _krev_milvus()
    sporsmal = data.get("sporsmal", "")
    filtre = data.get("filtre", {})
    antall = data.get("antall", 10)
    try:
        sporsmaal_vektor = _embedding_modell.encode(sporsmal, normalize_embeddings=True).tolist()
        uttrykk = _bygg_filter(filtre)
        _samling.load()
        sokepar = {"metric_type": "COSINE", "params": {"ef": 64}}
        sok_kwargs = dict(
            data=[sporsmaal_vektor],
            anns_field="vektor",
            param=sokepar,
            limit=antall * 3,
            output_fields=[
                "fil_id", "filnavn", "side_nummer", "tekst",
                "navn", "dato", "ytelse", "fylke", "dokumenttype",
            ],
        )
        if uttrykk:
            sok_kwargs["expr"] = uttrykk
        vektor_resultater = _samling.search(**sok_kwargs)
        bm25_resultater = _bm25_sok(sporsmal, antall * 3)
        with _bm25_lås:
            dokumenter = list(_bm25_dokumenter)
        kombinerte = rrf_fusjoner(
            vektor_resultater[0], bm25_resultater, dokumenter
        )[:antall]
        return {"resultater": kombinerte, "totalt": len(kombinerte)}
    except HTTPException:
        raise
    except Exception as feil:
        logger.error("Sokefeil: %s", feil)
        raise HTTPException(status_code=500, detail=str(feil))


@app.get("/helse")
async def helse():
    status = "klar" if (_milvus_tilgjengelig and _embedding_tilgjengelig) else "degradert"
    return {
        "status": status,
        "tjeneste": "sok",
        "milvus": "tilgjengelig" if _milvus_tilgjengelig else "utilgjengelig",
        "embedding_modell": "klar" if _embedding_tilgjengelig else "utilgjengelig",
        "dokumenter_i_bm25": len(_bm25_dokumenter),
    }


@app.get("/statistikk")
async def statistikk():
    _krev_milvus()
    return {
        "totalt_dokumenter": _samling.num_entities,
        "bm25_dokumenter": len(_bm25_dokumenter),
    }


# ------------------------------------------------------------------ #
#  Hjelpemetoder                                                        #
# ------------------------------------------------------------------ #

# Kanoniske lister fra delt/konstanter.py — én kilde til sannhet
from delt.konstanter import NORSKE_YTELSER as LOVLIGE_YTELSER
from delt.konstanter import NORSKE_FYLKER as LOVLIGE_FYLKER


def _bygg_filter(filtre: dict) -> str:
    betingelser = []
    ytelse = filtre.get("ytelse")
    if ytelse:
        if ytelse not in LOVLIGE_YTELSER:
            raise HTTPException(status_code=400, detail=f"Ugyldig ytelse: {ytelse!r}")
        betingelser.append(f'ytelse == "{ytelse}"')
    fylke = filtre.get("fylke")
    if fylke:
        if fylke not in LOVLIGE_FYLKER:
            raise HTTPException(status_code=400, detail=f"Ugyldig fylke: {fylke!r}")
        betingelser.append(f'fylke == "{fylke}"')
    fil_id = filtre.get("fil_id")
    if fil_id:
        if not fil_id.replace("-", "").isalnum() or len(fil_id) > 200:
            raise HTTPException(status_code=400, detail="Ugyldig fil_id")
        betingelser.append(f'fil_id == "{fil_id}"')
    return " && ".join(betingelser) if betingelser else ""


def _bm25_sok(sporsmal: str, antall: int) -> list:
    global bm25_indeks, _bm25_skitten
    with _bm25_lås:
        if _bm25_skitten and _bm25_dokumenter:
            bm25_indeks = BM25Okapi([d["tekst"].split() for d in _bm25_dokumenter])
            _bm25_skitten = False
        indeks = bm25_indeks
    if indeks is None:
        return []
    poeng = indeks.get_scores(sporsmal.split())
    return list(np.argsort(poeng)[::-1][:antall])


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)
