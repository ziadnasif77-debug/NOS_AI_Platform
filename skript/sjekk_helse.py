"""Sjekker status pa alle tjenester."""
import requests

TJENESTER = {
    "OCR (8001)":         "http://localhost:8001/helse",
    "NLP (8002)":         "http://localhost:8002/helse",
    "Sok (8003)":         "http://localhost:8003/helse",
    "API (8000)":         "http://localhost:8000/helse",
    "Gjennomgang (8004)": "http://localhost:8004/helse",
}

print("NAV Archive — Systemstatus\n" + "─" * 40)
for navn, url in TJENESTER.items():
    try:
        r = requests.get(url, timeout=5)
        data = r.json()
        print(f"✓ {navn}: {data.get('status', 'ok')}")
    except Exception as feil:
        print(f"✗ {navn}: IKKE TILGJENGELIG ({feil})")
