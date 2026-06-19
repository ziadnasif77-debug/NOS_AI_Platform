"""
Sender dokumenter med lav konfidens til Label Studio for korreksjon.
Kalles automatisk av OCR-tjenesten nar konfidens < 85%.
"""
import os
import requests

LABEL_STUDIO_URL = os.environ.get("LABEL_STUDIO_URL", "http://localhost:8080")
LABEL_STUDIO_API_KEY = os.environ.get("LABEL_STUDIO_API_KEY", "")
OCR_PROSJEKT_ID = os.environ.get("LABEL_STUDIO_OCR_PROSJEKT_ID", "1")

HEADERS = {
    "Authorization": f"Token {LABEL_STUDIO_API_KEY}",
    "Content-Type": "application/json",
}


def send_til_gjennomgang(
    fil_id: str,
    bilde_sti: str,
    raa_tekst: str,
    konfidens: float,
    metadata: dict
) -> bool:
    """
    Sender ett dokument til Label Studio for menneskelig korreksjon.
    Returnerer True hvis sending lyktes.
    """
    oppgave = {
        "data": {
            "bilde": bilde_sti,
            "tekst": raa_tekst,
            "fil_id": fil_id,
            "konfidens": round(konfidens * 100, 1),
            "navn": metadata.get("navn", ""),
            "dato": metadata.get("dato", ""),
            "ytelse": metadata.get("ytelse", ""),
            "fylke": metadata.get("fylke", ""),
        }
    }
    try:
        svar = requests.post(
            f"{LABEL_STUDIO_URL}/api/projects"
            f"/{OCR_PROSJEKT_ID}/import",
            headers=HEADERS,
            json=[oppgave],
            timeout=10
        )
        svar.raise_for_status()
        return True
    except requests.RequestException as feil:
        print(f"Kunne ikke sende til Label Studio: {feil}")
        return False
