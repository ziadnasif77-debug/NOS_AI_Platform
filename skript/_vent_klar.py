"""Skriver «klar» hvis dokument-API-et svarer og Borealis er lastet,
ellers «venter». Brukes av START_SERVER.bat for a vise fremdrift."""
import sys
import urllib.request

try:
    with urllib.request.urlopen("http://localhost:8600/hjelp", timeout=3) as r:
        import json
        data = json.load(r)
    sys.stdout.write("klar" if data.get("borealis") == "klar" else "venter")
except Exception:
    sys.stdout.write("venter")
