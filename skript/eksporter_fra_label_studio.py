"""
Eksporterer korreksjoner fra Label Studio og konverterer
til treningsformat for finjustering av TrOCR-NorHand og NB-BERT.
Kjores av: make eksporter-korreksjoner
Eller automatisk etter 500 korreksjoner.
"""
import os
import json
import requests
from pathlib import Path
from datetime import datetime

LABEL_STUDIO_URL = os.environ.get("LABEL_STUDIO_URL", "http://localhost:8080")
LABEL_STUDIO_API_KEY = os.environ.get("LABEL_STUDIO_API_KEY", "")
FINJUSTERING_STI = os.environ.get("FINJUSTERING_STI", "./data/finjustering")

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
                "fil_sti": bilde_url,
                "tekst": korrekt_tekst,
                "oppgave_id": oppgave.get("id"),
                "annotert_av": annotering.get("completed_by"),
                "tidsstempel": datetime.now().isoformat(),
            }
    return None


def konverter_til_nb_bert_format(oppgave: dict) -> dict | None:
    """
    Konverterer en Label Studio-oppgave til NB-BERT-treningsformat.
    NB-BERT forventer:
    {
        "tekst": "dokumenttekst",
        "etikett": "soknad" | "vedtak" | "korrespondanse"
    }
    """
    annoteringer = oppgave.get("annotations", [])
    if not annoteringer:
        return None
    annotering = annoteringer[0]
    resultater = annotering.get("result", [])
    for resultat in resultater:
        if resultat.get("type") == "choices":
            etikett = resultat.get("value", {}).get("choices", [None])[0]
            tekst = oppgave.get("data", {}).get("tekst", "")
            if etikett and tekst:
                return {
                    "tekst": tekst,
                    "etikett": etikett,
                    "oppgave_id": oppgave.get("id"),
                    "tidsstempel": datetime.now().isoformat(),
                }
    return None


def eksporter():
    """Hovedfunksjon — eksporterer alle korreksjoner."""
    Path(FINJUSTERING_STI).mkdir(parents=True, exist_ok=True)

    prosjekter = hent_prosjekter()
    print(f"Fant {len(prosjekter)} prosjekt(er) i Label Studio")

    trocr_data = []
    nb_bert_data = []

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

            nb_bert = konverter_til_nb_bert_format(oppgave)
            if nb_bert:
                nb_bert_data.append(nb_bert)

    tidsstempel = datetime.now().strftime("%Y%m%d_%H%M%S")

    if trocr_data:
        trocr_fil = f"{FINJUSTERING_STI}/trocr_{tidsstempel}.json"
        with open(trocr_fil, "w", encoding="utf-8") as f:
            json.dump(trocr_data, f, ensure_ascii=False, indent=2)
        print(f"\nTrOCR-treningsdata: {len(trocr_data)} eksempler -> {trocr_fil}")

    if nb_bert_data:
        nb_bert_fil = f"{FINJUSTERING_STI}/nb_bert_{tidsstempel}.json"
        with open(nb_bert_fil, "w", encoding="utf-8") as f:
            json.dump(nb_bert_data, f, ensure_ascii=False, indent=2)
        print(f"NB-BERT-treningsdata: {len(nb_bert_data)} eksempler -> {nb_bert_fil}")

    totalt = len(trocr_data) + len(nb_bert_data)
    print(f"\nTotalt eksportert: {totalt} korreksjoner")
    print("Kjor 'make finjuster' for a starte modelltrening.")
    return totalt


def etter_finjustering():
    """
    Kalles etter at finjuster.py er ferdig.
    Ber OCR-tjenesten laste inn oppdaterte modeller.
    Tilsvarer feedback-pilen i arkitektur__1_.svg som peker
    tilbake til lag 4 OCR — ikke til NLP.
    """
    ocr_url = os.environ.get("OCR_URL", "http://localhost:8001")
    try:
        svar = requests.post(
            f"{ocr_url}/last-inn-modeller-pa-nytt",
            timeout=60
        )
        svar.raise_for_status()
        print("OCR-tjeneste har lastet inn oppdaterte modeller")
    except requests.RequestException as feil:
        print(f"Kunne ikke varsle OCR-tjeneste: {feil}")


if __name__ == "__main__":
    totalt = eksporter()
    if totalt > 0:
        etter_finjustering()
