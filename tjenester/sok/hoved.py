import os
import sys
import uvicorn
from fastapi import FastAPI, HTTPException
from pymilvus import (
    connections, Collection, CollectionSchema,
    FieldSchema, DataType, utility
)
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi
import numpy as np

sys.path.insert(0, "/delt")
from delt.verktøy import konfigurer_logging

logger = konfigurer_logging("sok-tjeneste")
app = FastAPI(title="NAV Soketjeneste")

MODELLER_STI = os.environ.get("MODELLER_STI", "/modeller")
MILVUS_VERT = os.environ.get("MILVUS_VERT", "milvus")
MILVUS_PORT = int(os.environ.get("MILVUS_PORT", "19530"))
MILVUS_SAMLING = os.environ.get("MILVUS_SAMLING", "nav_dokumenter")

connections.connect(host=MILVUS_VERT, port=MILVUS_PORT)


def opprett_samling():
    if utility.has_collection(MILVUS_SAMLING):
        return Collection(MILVUS_SAMLING)
    felt = [
        FieldSchema("id", DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema("fil_id", DataType.VARCHAR, max_length=200),
        FieldSchema("filnavn", DataType.VARCHAR, max_length=500),
        FieldSchema("side_nummer", DataType.INT64),
        FieldSchema("tekst", DataType.VARCHAR, max_length=65535),
        FieldSchema("fodselsnummer", DataType.VARCHAR, max_length=20),
        FieldSchema("navn", DataType.VARCHAR, max_length=200),
        FieldSchema("dato", DataType.VARCHAR, max_length=50),
        FieldSchema("ytelse", DataType.VARCHAR, max_length=100),
        FieldSchema("fylke", DataType.VARCHAR, max_length=100),
        FieldSchema("dokumenttype", DataType.VARCHAR, max_length=100),
        FieldSchema("vektor", DataType.FLOAT_VECTOR, dim=1024),
    ]
    skjema = CollectionSchema(felt, "NAV historiske dokumenter")
    samling = Collection(MILVUS_SAMLING, skjema)
    samling.create_index(
        "vektor",
        {
            "index_type": "HNSW",
            "metric_type": "COSINE",
            "params": {"M": 16, "efConstruction": 200}
        }
    )
    return samling


samling = opprett_samling()

logger.info("Laster Qwen3-Embedding-0.6B...")
_embedding_enhet = "cuda" if torch.cuda.is_available() else "cpu"
logger.info(f"Embedding kjører på: {_embedding_enhet}")
embedding_modell = SentenceTransformer(
    f"{MODELLER_STI}/qwen3-embed",
    device=_embedding_enhet
)

bm25_korpus = []
bm25_fil_ids = []
bm25_indeks = None


@app.post("/indekser")
async def indekser(data: dict):
    global bm25_indeks, bm25_korpus, bm25_fil_ids
    tekst = data.get("tekst", "")
    metadata = data.get("metadata", {})
    try:
        vektor = embedding_modell.encode(
            tekst[:2048], normalize_embeddings=True
        ).tolist()
        samling.insert([{
            "fil_id": metadata.get("fil_id", ""),
            "filnavn": data.get("filnavn", ""),
            "side_nummer": metadata.get("side_nummer", 0),
            "tekst": tekst[:65000],
            "fodselsnummer": metadata.get("fodselsnummer") or "",
            "navn": metadata.get("navn") or "",
            "dato": metadata.get("dato") or "",
            "ytelse": metadata.get("ytelse") or "",
            "fylke": metadata.get("fylke") or "",
            "dokumenttype": metadata.get("dokumenttype") or "",
            "vektor": vektor,
        }])
        bm25_korpus.append(tekst.split())
        bm25_fil_ids.append(metadata.get("fil_id", ""))
        bm25_indeks = BM25Okapi(bm25_korpus)
        samling.flush()
        return {"status": "indeksert", "fil_id": metadata.get("fil_id")}
    except Exception as feil:
        logger.error(f"Indekseringsfeil: {feil}")
        raise HTTPException(status_code=500, detail=str(feil))


@app.post("/sok")
async def sok(data: dict):
    sporsmal = data.get("sporsmal", "")
    filtre = data.get("filtre", {})
    antall = data.get("antall", 10)
    try:
        sporsmaal_vektor = embedding_modell.encode(
            sporsmal, normalize_embeddings=True
        ).tolist()
        uttrykk = _bygg_filter(filtre)
        samling.load()
        sokepar = {"metric_type": "COSINE", "params": {"ef": 64}}
        sok_kwargs = dict(
            data=[sporsmaal_vektor],
            anns_field="vektor",
            param=sokepar,
            limit=antall * 3,
            output_fields=["fil_id", "filnavn", "side_nummer",
                           "tekst", "fodselsnummer", "navn",
                           "dato", "ytelse", "fylke", "dokumenttype"]
        )
        if uttrykk:
            sok_kwargs["expr"] = uttrykk
        vektor_resultater = samling.search(**sok_kwargs)
        bm25_resultater = _bm25_sok(sporsmal, antall * 3)
        kombinerte = _rrf_fusjoner(vektor_resultater[0], bm25_resultater)[:antall]
        return {"resultater": kombinerte, "totalt": len(kombinerte)}
    except Exception as feil:
        logger.error(f"Sokefeil: {feil}")
        raise HTTPException(status_code=500, detail=str(feil))


def _bygg_filter(filtre: dict) -> str:
    betingelser = []
    if filtre.get("ytelse"):
        betingelser.append(f'ytelse == "{filtre["ytelse"]}"')
    if filtre.get("fylke"):
        betingelser.append(f'fylke == "{filtre["fylke"]}"')
    if filtre.get("fodselsnummer"):
        betingelser.append(f'fodselsnummer == "{filtre["fodselsnummer"]}"')
    return " && ".join(betingelser) if betingelser else ""


def _bm25_sok(sporsmal: str, antall: int) -> list:
    if bm25_indeks is None:
        return []
    poeng = bm25_indeks.get_scores(sporsmal.split())
    topp_indekser = np.argsort(poeng)[::-1][:antall]
    return list(topp_indekser)


def _rrf_fusjoner(vektor_treff: list, bm25_treff: list, k: int = 60) -> list:
    poeng = {}
    for rang, treff in enumerate(vektor_treff):
        fil_id = treff.entity.get("fil_id")
        poeng[fil_id] = poeng.get(fil_id, 0) + 1.0 / (k + rang + 1)
    for rang, indeks in enumerate(bm25_treff):
        if indeks < len(bm25_fil_ids):
            fil_id = bm25_fil_ids[indeks]
            poeng[fil_id] = poeng.get(fil_id, 0) + 1.0 / (k + rang + 1)
    return sorted(poeng.items(), key=lambda x: x[1], reverse=True)


@app.get("/helse")
async def helse():
    return {
        "status": "ok",
        "tjeneste": "sok",
        "dokumenter_i_bm25": len(bm25_korpus)
    }


@app.get("/statistikk")
async def statistikk():
    return {
        "totalt_dokumenter": samling.num_entities,
        "bm25_dokumenter": len(bm25_korpus)
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)
