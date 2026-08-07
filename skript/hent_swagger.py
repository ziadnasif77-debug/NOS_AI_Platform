"""
Henter Swagger UI inn i nav-mappa, så `/dokumentasjon` virker uten
internett.

Hvorfor dette skriptet finnes (CLAUDE.md §1): dokumentasjonssiden lastet
stilarket og JavaScript-bundelen fra `cdn.jsdelivr.net`. På en server
uten utgående internett — som er hele poenget med at prosjektet skal
kunne kopieres til «en hvilken som helst server» — forsvant da HELE
endepunktlista. Siden svarte 200, og det som manglet var det siden
finnes for.

Samme mønster som `hent_lovtekst.py`: filene legges under `data/`, som
følger den kopierte mappa i stedet for git (de er for store for git,
akkurat som modellene og lovtekstene).

Bruk (fra D:\\nav):
    python skript/hent_swagger.py            # henter versjonen under
    python skript/hent_swagger.py 5.17.14    # eller en bestemt

Etterpå ligger filene i data/swagger/ og serveren tar dem derfra.
Skriptet skriver ut SHA-256 for hver fil, så det som ble hentet kan
kontrolleres mot det som blir liggende.
"""
import hashlib
import io
import os
import sys

import requests

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAPPE = os.path.join(ROT, "data", "swagger")

# Låst versjon, ikke «@5»: en bevegelig peker gjør at to kopier av
# nav-mappa kan ende med ulik Swagger uten at noen har endret noe.
STANDARDVERSJON = "5.17.14"

# Nøyaktig de to filene siden trenger. Ingen mappe hentes rått ned —
# det er disse serveren har en rute for, og lista er derfor også
# fasiten for hva som skal ligge der.
FILER = ("swagger-ui.css", "swagger-ui-bundle.js")


def _url(versjon: str, filnavn: str) -> str:
    return (f"https://cdn.jsdelivr.net/npm/swagger-ui-dist@{versjon}/"
            f"{filnavn}")


def hent(versjon: str = STANDARDVERSJON) -> int:
    os.makedirs(MAPPE, exist_ok=True)
    print(f"Henter Swagger UI {versjon} til {MAPPE}\n")
    for filnavn in FILER:
        url = _url(versjon, filnavn)
        print(f"  {filnavn} … ", end="", flush=True)
        svar = requests.get(url, timeout=60)
        svar.raise_for_status()
        innhold = svar.content
        with open(os.path.join(MAPPE, filnavn), "wb") as f:
            f.write(innhold)
        sum_ = hashlib.sha256(innhold).hexdigest()
        print(f"{len(innhold)/1024:.0f} kB   sha256 {sum_[:16]}…")

    with open(os.path.join(MAPPE, "VERSJON"), "w", encoding="utf-8") as f:
        f.write(versjon + "\n")
    print(f"\nFerdig. GET /dokumentasjon henter nå alt fra nav-mappa.")
    return 0


if __name__ == "__main__":
    # Æøå ut i en cmd-konsoll. Står BEVISST her og ikke på modulnivå:
    # en modul som bytter ut prosessens stdout ved import, river beina
    # under alle som importerer den — testene fanget nettopp det.
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace")
    versjon = sys.argv[1] if len(sys.argv) > 1 else STANDARDVERSJON
    try:
        sys.exit(hent(versjon))
    except requests.RequestException as feil:
        print(f"\nFEIL: klarte ikke å hente Swagger UI: {feil}")
        print("Har maskinen internett? Filene kan også kopieres manuelt "
              f"fra en annen nav-mappe: data/swagger/")
        sys.exit(1)
