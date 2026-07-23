"""
Sender et dårlig lest dokument til Label Studio for menneskelig
korreksjon — det første steget i treningsløkken.

Kalles av serverens auto-gjennomgang (dokument_api.py:
_kanskje_send_til_gjennomgang) i en bakgrunnstråd når en lesing er tom,
har lav OCR-konfidens, eller inneholder håndskrift. Best-effort: feiler
sendingen, forsinkes aldri svaret til klienten.
"""
import os
import shutil
import requests
from pathlib import Path

LABEL_STUDIO_URL = os.environ.get("LABEL_STUDIO_URL", "http://localhost:8080")
LABEL_STUDIO_API_KEY = os.environ.get("LABEL_STUDIO_API_KEY", "")
OCR_PROSJEKT_ID = os.environ.get("LABEL_STUDIO_OCR_PROSJEKT_ID", "1")
# Mappe der bildet legges så Label Studio kan vise det. Samme sti som
# eksporter_fra_label_studio.py leser fra (GJENNOMGANG_STI/bilder/<id>.png).
GJENNOMGANG_STI = os.environ.get("GJENNOMGANG_STI", "./data/gjennomgang")

HEADERS = {
    "Authorization": f"Token {LABEL_STUDIO_API_KEY}",
    "Content-Type": "application/json",
}


def _bygg_prediksjoner(regioner: list, bilde_dim) -> list:
    """Gjør OCR-ens regionbokser om til Label Studio-«predictions»:
    forhåndsmerkede rektangler på bildet (prosentkoordinater — derfor
    spiller det ingen rolle at oppgavebildet har annen DPI enn OCR-en).
    Etikett per boks: skriftslag fra OCR-en, «Uleselig» ved lav konfidens.
    Regionens egen tekst legges i meta, så den vises når boksen velges."""
    if not regioner or not bilde_dim:
        return []
    bredde, hoyde = bilde_dim
    if not bredde or not hoyde:
        return []
    resultater = []
    for i, region in enumerate(regioner):
        boks = region.get("boks") or []
        if len(boks) != 4:
            continue
        x0, y0, x1, y1 = boks
        if x1 <= x0 or y1 <= y0:
            continue
        konf = float(region.get("konfidens", 0.0))
        if konf < 0.35:
            etikett = "Uleselig"
        elif region.get("skrift") == "handskrift":
            etikett = "Håndskrift"
        else:
            etikett = "Trykt tekst"
        resultater.append({
            "id": f"ocr_{i}",
            "from_name": "omraade", "to_name": "bilde",
            "type": "rectanglelabels",
            "value": {
                "x": 100.0 * x0 / bredde, "y": 100.0 * y0 / hoyde,
                "width": 100.0 * (x1 - x0) / bredde,
                "height": 100.0 * (y1 - y0) / hoyde,
                "rotation": 0, "rectanglelabels": [etikett],
            },
            "original_width": bredde, "original_height": hoyde,
            "score": round(konf, 3),
            "meta": {"text": [region.get("tekst", "")]},
        })
    if not resultater:
        return []
    return [{"model_version": "auto-ocr", "result": resultater}]


def send_til_gjennomgang(
    fil_id: str,
    bilde_sti: str,
    raa_tekst: str,
    konfidens: float,
    metadata: dict,
    regioner: list | None = None,
    bilde_dim=None,
) -> bool:
    """
    Sender ett dokument til Label Studio for menneskelig korreksjon.
    Kopierer bildet til det delte volumet slik at Label Studio kan vise det.
    Med `regioner` + `bilde_dim` følger OCR-ens tekstbokser med som
    forhåndsmerkede områder på bildet. Returnerer True hvis sending lyktes.
    """
    # Kopier bilde til det delte volumet (montert i Label Studio som /label-studio/data)
    bilder_mappe = Path(GJENNOMGANG_STI) / "bilder"
    bilder_mappe.mkdir(parents=True, exist_ok=True)
    maal_sti = bilder_mappe / f"{fil_id}.png"
    try:
        shutil.copy2(bilde_sti, str(maal_sti))
        # Label Studio betjener lokale filer via /data/local-files/?d=<relativ-sti>
        ls_bilde_url = f"/data/local-files/?d=bilder/{fil_id}.png"
    except Exception as feil:
        print(f"Advarsel: Kunne ikke kopiere bilde til delt volum: {feil}")
        ls_bilde_url = bilde_sti  # Fallback — vil sannsynligvis ikke vises

    oppgave = {
        "data": {
            "bilde": ls_bilde_url,
            "tekst": raa_tekst,
            "fil_id": fil_id,
            "konfidens": round(konfidens * 100, 1),
            "navn": metadata.get("navn", ""),
            "dato": metadata.get("dato", ""),
            "ytelse": metadata.get("ytelse", ""),
            "fylke": metadata.get("fylke", ""),
        }
    }
    prediksjoner = _bygg_prediksjoner(regioner or [], bilde_dim)
    if prediksjoner:
        oppgave["predictions"] = prediksjoner
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
