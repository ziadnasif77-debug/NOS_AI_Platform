import os
import sys
import time
import threading
import torch
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from rank_bm25 import BM25Okapi
import numpy as np

sys.path.insert(0, "/app")
from delt.verktøy import konfigurer_logging

logger = konfigurer_logging("sok-tjeneste")

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

bm25_korpus: list = []
bm25_fil_ids: list = []
bm25_indeks = None
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
        FieldSchema("id",            DataType.INT64,         is_primary=True, auto_id=True),
        FieldSchema("fil_id",        DataType.VARCHAR,        max_length=200),
        FieldSchema("filnavn",       DataType.VARCHAR,        max_length=500),
        FieldSchema("side_nummer",   DataType.INT64),
        FieldSchema("tekst",         DataType.VARCHAR,        max_length=65535),
        FieldSchema("fodselsnummer", DataType.VARCHAR,        max_length=20),
        FieldSchema("navn",          DataType.VARCHAR,        max_length=200),
        FieldSchema("dato",          DataType.VARCHAR,        max_length=50),
        FieldSchema("ytelse",        DataType.VARCHAR,        max_length=100),
        FieldSchema("fylke",         DataType.VARCHAR,        max_length=100),
        FieldSchema("dokumenttype",  DataType.VARCHAR,        max_length=100),
        FieldSchema("vektor",        DataType.FLOAT_VECTOR,   dim=1024),
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
    global bm25_indeks, bm25_korpus, bm25_fil_ids
    try:
        samling.load()
        hentet = []
        grense, offset = 1000, 0
        while True:
            batch = samling.query(
                expr='fil_id != ""',
                output_fields=["fil_id", "tekst"],
                limit=grense,
                offset=offset,
            )
            if not batch:
                break
            hentet.extend(batch)
            offset += len(batch)
            if len(batch) < grense:
                break
        bm25_korpus = [d["tekst"].split() for d in hentet]
        bm25_fil_ids = [d["fil_id"] for d in hentet]
        if bm25_korpus:
            bm25_indeks = BM25Okapi(bm25_korpus)
        logger.info("BM25 gjenoppbygd: %d dokumenter.", len(bm25_korpus))
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
    global bm25_indeks, bm25_korpus, bm25_fil_ids
    tekst = data.get("tekst", "")
    metadata = data.get("metadata", {})
    try:
        vektor = _embedding_modell.encode(tekst[:2048], normalize_embeddings=True).tolist()
        _samling.insert([{
            "fil_id":        metadata.get("fil_id", ""),
            "filnavn":       data.get("filnavn", ""),
            "side_nummer":   metadata.get("side_nummer", 0),
            "tekst":         tekst[:65000],
            "fodselsnummer": metadata.get("fodselsnummer") or "",
            "navn":          metadata.get("navn") or "",
            "dato":          metadata.get("dato") or "",
            "ytelse":        metadata.get("ytelse") or "",
            "fylke":         metadata.get("fylke") or "",
            "dokumenttype":  metadata.get("dokumenttype") or "",
            "vektor":        vektor,
        }])
        with _bm25_lås:
            bm25_korpus.append(tekst.split())
            bm25_fil_ids.append(metadata.get("fil_id", ""))
            bm25_indeks = BM25Okapi(bm25_korpus)
        _samling.flush()
        return {"status": "indeksert", "fil_id": metadata.get("fil_id")}
    except HTTPException:
        raise
    except Exception as feil:
        logger.error("Indekseringsfeil: %s", feil)
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
                "fodselsnummer", "navn", "dato", "ytelse", "fylke", "dokumenttype",
            ],
        )
        if uttrykk:
            sok_kwargs["expr"] = uttrykk
        vektor_resultater = _samling.search(**sok_kwargs)
        bm25_resultater = _bm25_sok(sporsmal, antall * 3)
        kombinerte = _rrf_fusjoner(vektor_resultater[0], bm25_resultater)[:antall]
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
        "dokumenter_i_bm25": len(bm25_korpus),
    }


@app.get("/statistikk")
async def statistikk():
    _krev_milvus()
    return {
        "totalt_dokumenter": _samling.num_entities,
        "bm25_dokumenter": len(bm25_korpus),
    }


# ------------------------------------------------------------------ #
#  Hjelpemetoder                                                        #
# ------------------------------------------------------------------ #

def _bygg_filter(filtre: dict) -> str:
    betingelser = []
    if filtre.get("ytelse"):
        betingelser.append(f'ytelse == "{filtre["ytelse"]}"')
    if filtre.get("fylke"):
        betingelser.append(f'fylke == "{filtre["fylke"]}"')
    if filtre.get("fodselsnummer"):
        betingelser.append(f'fodselsnummer == "{filtre["fodselsnummer"]}"')
    if filtre.get("fil_id"):
        betingelser.append(f'fil_id == "{filtre["fil_id"]}"')
    return " && ".join(betingelser) if betingelser else ""


def _bm25_sok(sporsmal: str, antall: int) -> list:
    if bm25_indeks is None:
        return []
    poeng = bm25_indeks.get_scores(sporsmal.split())
    return list(np.argsort(poeng)[::-1][:antall])


def _rrf_fusjoner(vektor_treff: list, bm25_treff: list, k: int = 60) -> list:
    poeng: dict = {}
    for rang, treff in enumerate(vektor_treff):
        fil_id = treff.entity.get("fil_id")
        poeng[fil_id] = poeng.get(fil_id, 0) + 1.0 / (k + rang + 1)
    for rang, indeks in enumerate(bm25_treff):
        if indeks < len(bm25_fil_ids):
            fil_id = bm25_fil_ids[indeks]
            poeng[fil_id] = poeng.get(fil_id, 0) + 1.0 / (k + rang + 1)
    return sorted(poeng.items(), key=lambda x: x[1], reverse=True)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)
