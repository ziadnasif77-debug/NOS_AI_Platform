"""
Eksporterer korreksjoner fra Label Studio og konverterer til
treningsformat for finjustering av TrOCR-NorHand (håndskrift).

Bare tekstkorreksjonene (textarea) hentes ut — det er den eneste modellen
serveren faktisk bruker. Tidligere ble også dokumenttype-valg (choices)
eksportert til NB-BERT, men den modellen er fjernet (2026-07-21).

Kjøres MANUELT: `make eksporter-korreksjoner`, eller via
`kjor_treningslop.py`. Det finnes ingen automatisk «etter N
korreksjoner»-utløser i koden (den påstanden var aldri implementert).
"""
import os
import json
import requests
from pathlib import Path
from datetime import datetime

LABEL_STUDIO_URL = os.environ.get("LABEL_STUDIO_URL", "http://localhost:8080")
LABEL_STUDIO_API_KEY = os.environ.get("LABEL_STUDIO_API_KEY", "")
FINJUSTERING_STI = os.environ.get("FINJUSTERING_STI", "./data/finjustering")
# Bildene Label Studio viser ble kopiert hit av send_til_label_studio.py
# (GJENNOMGANG_STI/bilder/<id>.png), og eksponert som URL-en
# «/data/local-files/?d=bilder/<id>.png». Vi må oversette den URL-en
# tilbake til den faktiske filstien, ellers får finjuster.py en URL den
# ikke kan åpne → trente før på blanke bilder (R-fiks 2026-07-20).
GJENNOMGANG_STI = os.environ.get("GJENNOMGANG_STI", "./data/gjennomgang")


def _lokal_bildesti(bilde_url: str) -> str:
    """Oversetter en Label Studio local-files-URL til en ekte filsti.
    «/data/local-files/?d=bilder/x.png» → «<GJENNOMGANG_STI>/bilder/x.png».
    Ukjente former returneres uendret (kan allerede være en filsti)."""
    if not bilde_url:
        return ""
    if "?d=" in bilde_url:
        rel = bilde_url.split("?d=", 1)[1].split("&", 1)[0]
        try:
            from urllib.parse import unquote
            rel = unquote(rel)
        except Exception:
            pass
        return str(Path(GJENNOMGANG_STI) / rel)
    return bilde_url

HEADERS = {
    "Authorization": f"Token {LABEL_STUDIO_API_KEY}",
    "Content-Type": "application/json",
}


def hent_prosjekter() -> list:
    """Henter alle Label Studio-prosjekter."""
    try:
        svar = requests.get(
            f"{LABEL_STUDIO_URL}/api/projects/",
            headers=HEADERS,
            timeout=10
        )
        svar.raise_for_status()
        return svar.json().get("results", [])
    except requests.RequestException as feil:
        print(f"Kunne ikke hente prosjekter: {feil}")
        return []


def hent_fullforte_oppgaver(prosjekt_id: int) -> list:
    """Henter alle fullforte annoteringer fra ett prosjekt."""
    try:
        svar = requests.get(
            f"{LABEL_STUDIO_URL}/api/tasks"
            f"?project={prosjekt_id}&annotation_results=true",
            headers=HEADERS,
            timeout=30
        )
        svar.raise_for_status()
        return svar.json().get("tasks", [])
    except requests.RequestException as feil:
        print(f"Kunne ikke hente oppgaver for prosjekt {prosjekt_id}: {feil}")
        return []


def konverter_til_trocr_format(oppgave: dict) -> dict | None:
    """
    Konverterer en Label Studio-oppgave til TrOCR-treningsformat.
    TrOCR forventer:
    {
        "fil_sti": "sti/til/bilde.png",
        "tekst": "korrekt tekst fra annotator"
    }
    """
    annoteringer = oppgave.get("annotations", [])
    if not annoteringer:
        return None
    annotering = annoteringer[0]
    resultater = annotering.get("result", [])
    for resultat in resultater:
        if resultat.get("type") == "textarea":
            korrekt_tekst = resultat.get("value", {}).get("text", [""])[0]
            bilde_url = oppgave.get("data", {}).get("bilde", "")
            return {
                "fil_sti": _lokal_bildesti(bilde_url),
                "tekst": korrekt_tekst,
                "oppgave_id": oppgave.get("id"),
                "annotert_av": annotering.get("completed_by"),
                "tidsstempel": datetime.now().isoformat(),
            }
    return None


def eksporter():
    """Hovedfunksjon — eksporterer alle korreksjoner."""
    Path(FINJUSTERING_STI).mkdir(parents=True, exist_ok=True)

    prosjekter = hent_prosjekter()
    print(f"Fant {len(prosjekter)} prosjekt(er) i Label Studio")

    trocr_data = []

    for prosjekt in prosjekter:
        prosjekt_id = prosjekt["id"]
        prosjekt_navn = prosjekt["title"]
        print(f"Behandler: {prosjekt_navn} (ID: {prosjekt_id})")

        oppgaver = hent_fullforte_oppgaver(prosjekt_id)
        print(f"  -> {len(oppgaver)} fullforte oppgaver")

        for oppgave in oppgaver:
            trocr = konverter_til_trocr_format(oppgave)
            if trocr:
                trocr_data.append(trocr)

    tidsstempel = datetime.now().strftime("%Y%m%d_%H%M%S")

    if trocr_data:
        trocr_fil = f"{FINJUSTERING_STI}/trocr_{tidsstempel}.json"
        with open(trocr_fil, "w", encoding="utf-8") as f:
            json.dump(trocr_data, f, ensure_ascii=False, indent=2)
        print(f"\nTrOCR-treningsdata: {len(trocr_data)} eksempler -> {trocr_fil}")

    print(f"\nTotalt eksportert: {len(trocr_data)} korreksjoner")
    print("Kjor 'make finjuster' for a starte modelltrening.")
    return len(trocr_data)


if __name__ == "__main__":
    totalt = eksporter()
    if totalt > 0:
        print("\nEtter finjustering: start serveren på nytt for å ta den "
              "nytrente modellen i bruk (modeller lastes ved oppstart).")
