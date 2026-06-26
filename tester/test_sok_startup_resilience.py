"""
Regresjonstest for P1: sok-tjenesten skal ikke kræsje ved Milvus-feil ved oppstart.

Verifiserer:
- _koble_til_milvus() gir opp etter timeout og returnerer False (ikke exception)
- /helse returnerer "degradert" når Milvus er utilgjengelig
- /indekser returnerer 503 når Milvus er utilgjengelig
- /sok returnerer 503 når Milvus er utilgjengelig
"""
import sys
import os
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock tunge avhengigheter som ikke er installert i testmiljø
for _dep in ("torch", "pymilvus", "sentence_transformers", "rank_bm25", "numpy"):
    if _dep not in sys.modules:
        sys.modules[_dep] = MagicMock()

# torch.cuda.is_available() må returnere bool
sys.modules["torch"].cuda = MagicMock()
sys.modules["torch"].cuda.is_available = MagicMock(return_value=False)


def _patch_milvus_utilgjengelig():
    """Returnerer en patch som gjør at alle Milvus-kall feiler."""
    return patch(
        "pymilvus.connections.connect",
        side_effect=Exception("Milvus ikke tilgjengelig (simulert)"),
    )


def test_koble_til_milvus_gir_opp_etter_timeout():
    """_koble_til_milvus() skal returnere False (ikke raise) ved timeout."""
    with patch.dict(os.environ, {"MILVUS_RETRY_SEKUNDER": "2"}):
        import importlib
        import tjenester.sok.hoved as mod
        importlib.reload(mod)

        with _patch_milvus_utilgjengelig():
            resultat = mod._koble_til_milvus()

    assert resultat is False, "_koble_til_milvus() skal returnere False, ikke raise exception"


def test_helse_degradert_nar_milvus_utilgjengelig():
    """_milvus_tilgjengelig=False → /helse skal rapportere 'degradert'."""
    import tjenester.sok.hoved as mod
    original = mod._milvus_tilgjengelig

    try:
        mod._milvus_tilgjengelig = False
        mod._embedding_tilgjengelig = True

        from fastapi.testclient import TestClient
        client = TestClient(mod.app, raise_server_exceptions=False)
        svar = client.get("/helse")

        assert svar.status_code == 200
        data = svar.json()
        assert data["status"] == "degradert"
        assert data["milvus"] == "utilgjengelig"
        assert data["embedding_modell"] == "klar"
    finally:
        mod._milvus_tilgjengelig = original


def test_indekser_503_nar_milvus_utilgjengelig():
    """/indekser skal returnere 503 når Milvus ikke er tilgjengelig."""
    import tjenester.sok.hoved as mod
    original = mod._milvus_tilgjengelig

    try:
        mod._milvus_tilgjengelig = False
        mod._samling = None

        from fastapi.testclient import TestClient
        client = TestClient(mod.app, raise_server_exceptions=False)
        svar = client.post("/indekser", json={"tekst": "test", "metadata": {}})

        assert svar.status_code == 503
        assert svar.json()["detail"]["grunn"] == "milvus_utilgjengelig"
    finally:
        mod._milvus_tilgjengelig = original


def test_sok_503_nar_milvus_utilgjengelig():
    """/sok skal returnere 503 når Milvus ikke er tilgjengelig."""
    import tjenester.sok.hoved as mod
    original = mod._milvus_tilgjengelig

    try:
        mod._milvus_tilgjengelig = False
        mod._samling = None

        from fastapi.testclient import TestClient
        client = TestClient(mod.app, raise_server_exceptions=False)
        svar = client.post("/sok", json={"sporsmal": "Ola Nordmann"})

        assert svar.status_code == 503
        assert svar.json()["detail"]["grunn"] == "milvus_utilgjengelig"
    finally:
        mod._milvus_tilgjengelig = original
