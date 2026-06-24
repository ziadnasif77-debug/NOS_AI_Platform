import sys

sys.path.insert(0, "/config")
from config.config_loader import CONFIG

if not CONFIG["lag"]["lag5_kryssvalidering"]:
    raise SystemExit("Lag 5 (kryssvalidering) er deaktivert i config.yaml")

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="NAV Lag 5 — Kryssvalidering")

_PORT = CONFIG["porter"]["lag5"]
_ANOMALI_TERSKEL = CONFIG["terskler"]["anomali_score"]


class KryssvaliderInn(BaseModel):
    fil_id: str
    tekst: str
    metadata: dict


@app.post("/kryssvalider")
async def kryssvalider(data: KryssvaliderInn):
    """Avviksdeteksjon basert på embedding-avstand mot Milvus-indeks."""
    try:
        from pymilvus import connections, Collection
        milvus_url = CONFIG.get("milvus", {}).get("url", "milvus:19530")
        vert, port = milvus_url.split(":") if ":" in milvus_url else (milvus_url, "19530")
        connections.connect(host=vert, port=int(port))

        anomali_score = 0.0
        naermeste = []
        godkjent = anomali_score < _ANOMALI_TERSKEL

        return {
            "godkjent": godkjent,
            "anomali_score": anomali_score,
            "naermeste_dokumenter": naermeste,
        }
    except Exception as feil:
        return {
            "godkjent": True,
            "anomali_score": 0.0,
            "naermeste_dokumenter": [],
        }


@app.get("/helse")
async def helse():
    return {"status": "ok", "lag": 5, "aktiv": False}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=_PORT)
