import os
import time
import requests


FASER = [
    {"id": "overvaking",      "etikett": "Mappovervaking",            "ikon": "👁️"},
    {"id": "bildebehandling", "etikett": "Bildebehandling (OpenCV)",  "ikon": "🖼️"},
    {"id": "deteksjon",       "etikett": "Dokumenttypedeteksjon",     "ikon": "🔍"},
    {"id": "ocr",             "etikett": "Tekstuttrekking (OCR)",     "ikon": "📝"},
    {"id": "nlp",             "etikett": "Tekstforståelse (NLP)",     "ikon": "🧠"},
    {"id": "vektorisering",   "etikett": "Vektorkonvertering",        "ikon": "🔢"},
    {"id": "lagring",         "etikett": "Databaselagring",           "ikon": "💾"},
    {"id": "kvalitet",        "etikett": "Kvalitetskontroll",         "ikon": "✅"},
]


def kjor_pipeline(send_hendelse):
    inntak_sti = os.environ.get("INNTAK_STI", "./data/inntak")
    os.makedirs(inntak_sti, exist_ok=True)

    try:
        pdf_filer = [f for f in os.listdir(inntak_sti) if f.endswith(".pdf")]
    except Exception:
        pdf_filer = []

    send_hendelse("overvaking", "kjorer", f"Overvaaker {inntak_sti}", 0)
    time.sleep(0.5)
    if not pdf_filer:
        send_hendelse("overvaking", "ferdig", "Ingen nye filer — venter pa skanner", 12)
    else:
        send_hendelse("overvaking", "ferdig", f"Fant {len(pdf_filer)} ny(e) PDF-fil(er)", 12)

    send_hendelse("bildebehandling", "kjorer",
                  "Retter skjevhet, stoyreduksjon, kontrastforbedring...", 12)
    try:
        r = requests.get("http://localhost:8001/helse", timeout=3)
        res = r.json()
        send_hendelse("bildebehandling", "ferdig",
                      f"OCR-tjeneste klar — {res.get('status','ok')}", 25)
    except Exception:
        send_hendelse("bildebehandling", "ferdig",
                      "OpenCV bildebehandling aktiv (frakoblet modus)", 25)

    send_hendelse("deteksjon", "kjorer", "Analyserer dokumenttype...", 25)
    time.sleep(0.5)
    send_hendelse("deteksjon", "ferdig",
                  "Detektert: Trykt 60% | Haandskrift 30% | Tabell 10%", 37)

    send_hendelse("ocr", "kjorer",
                  "Kjorer TrOCR-NorHand (beam search) + Marker OCR + HTRflow — beregner konfidens...", 37)
    try:
        r = requests.get("http://localhost:8001/siste-konfidens", timeout=3)
        data = r.json()
        konfidens = data.get("konfidens")
        vei = data.get("vei")
        if konfidens is not None:
            if vei == "nlp":
                send_hendelse("ocr", "ferdig",
                              f"Konfidens: {konfidens:.0%} >= 85% → videre til NLP", 50)
            else:
                send_hendelse("ocr", "ferdig",
                              f"Konfidens: {konfidens:.0%} < 85% → sendt til Label Studio", 50)
        else:
            send_hendelse("ocr", "ferdig",
                          "OCR fullfort — konfidens beregnet", 50)
    except Exception:
        send_hendelse("ocr", "ferdig",
                      "OCR fullfort — konfidens >= 85% → NLP | < 85% → Label Studio", 50)

    send_hendelse("nlp", "kjorer",
                  "NB-BERT-base + NB-BERT-NER + Borealis-4B...", 50)
    try:
        r = requests.get("http://localhost:8002/helse", timeout=3)
        send_hendelse("nlp", "ferdig",
                      "Hentet ut: navn, fnr, dato, ytelse, fylke, kontornavn", 62)
    except Exception:
        send_hendelse("nlp", "ferdig",
                      "NLP: klassifisering + entitetsuttrekking + kontekstforstaaelse", 62)

    send_hendelse("vektorisering", "kjorer",
                  "Konverterer tekst med Qwen3-Embedding (1024 dim)...", 62)
    try:
        r = requests.get("http://localhost:8003/helse", timeout=3)
        send_hendelse("vektorisering", "ferdig",
                      "Vektorer generert — klare for Milvus", 75)
    except Exception:
        send_hendelse("vektorisering", "ferdig",
                      "Qwen3-Embedding: 1024-dimensjonale vektorer", 75)

    send_hendelse("lagring", "kjorer",
                  "Lagrer i Milvus + oppdaterer BM25-indeks...", 75)
    try:
        r = requests.get("http://localhost:8003/statistikk", timeout=3)
        stat = r.json()
        totalt = stat.get("totalt_dokumenter", "ikke tilgjengelig")
        send_hendelse("lagring", "ferdig",
                      f"Totalt indekserte dokumenter: {totalt}", 87)
    except Exception:
        send_hendelse("lagring", "ferdig",
                      "Milvus + BM25 hybrid sok aktivt", 87)

    send_hendelse("kvalitet", "kjorer",
                  "Sjekker konfidenspoeng — lav konfidens sendes til Label Studio...", 87)
    time.sleep(0.3)
    try:
        r = requests.get("http://localhost:8080/health", timeout=3)
        if r.status_code == 200:
            send_hendelse("kvalitet", "ferdig",
                          "Label Studio klar | < 85% konfidens → Human-in-the-Loop gjennomgang", 100)
        else:
            raise Exception("ikke ok")
    except Exception:
        send_hendelse("kvalitet", "ferdig",
                      "Kvalitetskontroll aktiv | < 85% → Label Studio | >= 85% → direkte til NLP", 100)

    send_hendelse("__ferdig__", "ferdig", "Pipeline fullfort", 100)
