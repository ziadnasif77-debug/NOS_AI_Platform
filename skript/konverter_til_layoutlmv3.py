"""
Konverterer Label Studio-eksport til LayoutLMv3-treningsformat.
Tilsvarer Label_studio_to_layoutLMV3.py fra AI_MODEL-prosjektet.

Bruk: python skript/konverter_til_layoutlmv3.py
Eller: make konverter-annotasjoner
"""
import os
import json
from pathlib import Path
from datetime import datetime

FINJUSTERING_STI = os.environ.get("FINJUSTERING_STI", "./data/finjustering")

ETIKETT_MAP = {
    "NAVN": 0,
    "FODSELSNUMMER": 1,
    "DATO": 2,
    "ADRESSE": 3,
    "SIGNATUR": 4,
    "O": 5,
}


def konverter_label_studio_til_layoutlmv3(label_studio_fil: str) -> list:
    """
    Les Label Studio JSON-eksport og konverter til LayoutLMv3-format:
    {
        "bilde_sti": "...",
        "tokens": ["TOKEN1", ...],
        "bokser": [[x0, y0, x1, y1], ...],
        "etiketter": [0, 5, 5, 1, ...]  // etter ETIKETT_MAP
    }
    """
    with open(label_studio_fil, encoding="utf-8") as f:
        data = json.load(f)

    treningsdata = []
    for oppgave in data:
        bilde_sti = oppgave.get("data", {}).get("bilde", "")
        tokens = []
        bokser = []
        etiketter = []

        annoteringer = oppgave.get("annotations", [])
        if not annoteringer:
            continue

        for resultat in annoteringer[0].get("result", []):
            verdi = resultat.get("value", {})
            tekst_liste = verdi.get("text", [])
            label_liste = verdi.get("labels", [])
            x = verdi.get("x", 0)
            y = verdi.get("y", 0)
            w = verdi.get("width", 0)
            h = verdi.get("height", 0)

            tekst = tekst_liste[0] if tekst_liste else ""
            etikett = label_liste[0] if label_liste else "O"

            tokens.append(tekst)
            bokser.append([int(x), int(y), int(x + w), int(y + h)])
            etiketter.append(ETIKETT_MAP.get(etikett, 5))

        if tokens:
            treningsdata.append({
                "bilde_sti": bilde_sti,
                "tokens": tokens,
                "bokser": bokser,
                "etiketter": etiketter,
            })

    return treningsdata


def kjor():
    Path(FINJUSTERING_STI).mkdir(parents=True, exist_ok=True)

    # Finn Label Studio-eksporten (den rå LS-JSON-en med annotasjoner).
    # R-fiks 2026-07-20: ekskluder ALLE avledede filer, ikke bare
    # layoutlmv3_. Eksporteren skriver også trocr_*.json og nb_bert_*.json
    # til samme mappe — de mangler rektangel-annotasjonene og ga «0
    # eksempler» i stillhet når de ble plukket opp her.
    AVLEDEDE = ("layoutlmv3_", "trocr_", "nb_bert_")
    ls_filer = [f for f in Path(FINJUSTERING_STI).glob("*.json")
                if not f.name.startswith(AVLEDEDE)]

    if not ls_filer:
        print(f"Ingen rå Label Studio-eksport funnet i {FINJUSTERING_STI}")
        print("Eksporter prosjektet fra Label Studio (JSON) og legg filen "
              "i data/finjustering/ — IKKE trocr_/nb_bert_-filene fra "
              "eksporter-scriptet, de er et annet format.")
        return

    alle_data = []
    for fil in ls_filer:
        print(f"Konverterer: {fil.name}")
        data = konverter_label_studio_til_layoutlmv3(str(fil))
        alle_data.extend(data)
        print(f"  → {len(data)} eksempler")

    # R-fiks 2026-07-20: si tydelig fra i stedet for å skrive en tom fil.
    # 0 eksempler betyr nesten alltid at filene ikke var ekte LS-eksporter
    # (feil format / manglende annotasjoner) — ikke skriv en «vellykket»
    # tom treningsfil som senere gir en meningsløs treningskjøring.
    if not alle_data:
        print(f"\n0 eksempler etter konvertering av {len(ls_filer)} fil(er). "
              "Fant ingen gyldige LayoutLMv3-annotasjoner (rektangler + "
              "etiketter). Sjekk at filene er rå Label Studio-eksporter. "
              "Skriver INGEN treningsfil.")
        return

    tidsstempel = datetime.now().strftime("%Y%m%d_%H%M%S")
    utgang_fil = f"{FINJUSTERING_STI}/layoutlmv3_{tidsstempel}.json"
    with open(utgang_fil, "w", encoding="utf-8") as f:
        json.dump(alle_data, f, ensure_ascii=False, indent=2)

    print(f"\nTotalt: {len(alle_data)} eksempler → {utgang_fil}")
    print("Kjør 'make finjuster' for å trene LayoutLMv3 på disse dataene")


if __name__ == "__main__":
    kjor()
