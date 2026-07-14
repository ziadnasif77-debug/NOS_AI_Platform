"""
Hybrid-fusjon (RRF) og resultatformatering for søketjenesten.

Skilt ut fra hoved.py uten tunge avhengigheter (torch/milvus) slik at
logikken kan enhetstestes direkte.
"""

RRF_K = 60

_METADATA_FELT = ["filnavn", "side_nummer", "navn", "dato",
                  "ytelse", "fylke", "dokumenttype"]


def rrf_fusjoner(vektor_treff: list, bm25_treff: list,
                 bm25_dokumenter: list, k: int = RRF_K) -> list:
    """
    Reciprocal Rank Fusion over vektortreff (Milvus-hits) og BM25-treff
    (indekser inn i bm25_dokumenter). Returnerer KOMPLETTE dokumenter
    sortert etter fusjonert score — ikke bare id-er.

    bm25_dokumenter: liste av {"fil_id": ..., "tekst": ...}
    """
    poeng: dict = {}
    dokumenter: dict = {}

    for rang, treff in enumerate(vektor_treff):
        fil_id = treff.entity.get("fil_id")
        poeng[fil_id] = poeng.get(fil_id, 0) + 1.0 / (k + rang + 1)
        if fil_id not in dokumenter:
            dokumenter[fil_id] = _fra_vektor_treff(fil_id, treff)

    for rang, indeks in enumerate(bm25_treff):
        if indeks >= len(bm25_dokumenter):
            continue
        dok = bm25_dokumenter[indeks]
        fil_id = dok["fil_id"]
        poeng[fil_id] = poeng.get(fil_id, 0) + 1.0 / (k + rang + 1)
        if fil_id not in dokumenter:
            # Kun BM25-treff: vi har tekst men ikke Milvus-metadata
            dokumenter[fil_id] = {
                "fil_id": fil_id,
                "utdrag": dok.get("tekst", "")[:300],
                **{felt: None for felt in _METADATA_FELT},
            }

    rangert = sorted(poeng.items(), key=lambda x: x[1], reverse=True)
    return [
        {**dokumenter[fil_id], "score": round(score, 6)}
        for fil_id, score in rangert
    ]


def _fra_vektor_treff(fil_id, treff) -> dict:
    dok = {"fil_id": fil_id,
           "utdrag": (treff.entity.get("tekst") or "")[:300]}
    for felt in _METADATA_FELT:
        dok[felt] = treff.entity.get(felt)
    return dok
