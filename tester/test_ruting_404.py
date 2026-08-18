"""
404-svaret skal si HVA som kom inn (R235).

Målt to ganger fra en UiPath-robot: nøkkelen ble godtatt, forespørselen
avvist på 0 ms, og svaret listet opp de gyldige stiene — uten å si at
det var STIEN som var feil. Serverens egen tilgangslogg var eneste sted
sannheten sto: `"sti": "/"`.

Den vanligste årsaken er at basis-URL-en settes i en variabel og
endepunkt-feltet står tomt. Da hjelper en liste over gyldige stier
ingenting; det som hjelper er å få vite at serveren mottok «/».
"""
import json
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")


from dokument_api import ruting_404                            # noqa: E402


def test_roten_sier_at_endepunktet_mangler():
    for sti in ("", "/"):
        svar = ruting_404(sti)
        assert svar["mottatt_sti"] == "/"
        assert "mangler endepunktet" in svar["hint"]


def test_feil_versaler_sies_rett_ut():
    """«/Spor» er den andre vanlige feilen: stiene er små bokstaver."""
    svar = ruting_404("/Spor")
    assert svar["mottatt_sti"] == "/Spor"
    assert "smaa bokstaver" in svar["hint"]


def test_feilmeldingen_er_uendret_for_gamle_klienter():
    """Additivt: en klient som bare leste «feil», ser det samme som før."""
    svar = ruting_404("/tull")
    assert svar["feil"].startswith("Bruk POST /dokument")
    assert json.dumps(svar)          # serialiserbart
