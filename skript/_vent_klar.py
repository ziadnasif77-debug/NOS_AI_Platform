# -*- coding: utf-8 -*-
"""Skriver "klar" til stdout naar Borealis er ferdig lastet (POST /spor klar),
ellers "laster" (server oppe, modell lastes) eller "nede" (server svarer ikke).
Brukes av START_SERVER.bat sin ventelokke. Kun stdlib (ingen pakke-avhengighet)."""
import sys
import io
import os
import json
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PORT = os.environ.get("DOKUMENT_API_PORT",
                      os.environ.get("UIPATH_API_PORT", "8600"))

try:
    with urllib.request.urlopen(
        f"http://127.0.0.1:{PORT}/hjelp", timeout=2
    ) as svar:
        data = json.loads(svar.read().decode("utf-8", "replace"))
    print("klar" if data.get("borealis") == "klar" else "laster")
except Exception:
    print("nede")
