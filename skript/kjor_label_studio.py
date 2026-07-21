# -*- coding: utf-8 -*-
"""Portabel Label Studio-starter.

Kjorer entry-pointet `label_studio.server:main` via prosjektets EGEN .pyruntime,
med data-katalogen INNE i nav (LABEL_STUDIO_BASE_DATA_DIR = nav\\data\\label-studio)
slik at alt folger en mappe-kopi. Uten dette havner Label Studio sin database og
opplastede bilder i brukerprofilen (C:\\Users\\...\\AppData\\Local\\label-studio).

Bruk:
    .pyruntime\\python.exe skript\\kjor_label_studio.py            # start paa :8080
    .pyruntime\\python.exe skript\\kjor_label_studio.py version    # bare versjon
"""
import io
import os
import sys

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Data-katalog nav-lokal (kan overstyres utenfra av .bat-en).
os.environ.setdefault(
    "LABEL_STUDIO_BASE_DATA_DIR",
    os.path.join(ROT, "data", "label-studio"))
os.makedirs(os.environ["LABEL_STUDIO_BASE_DATA_DIR"], exist_ok=True)

from label_studio.server import main  # noqa: E402


if __name__ == "__main__":
    # Ingen argumenter -> start serveren paa valgt port.
    if len(sys.argv) == 1:
        port = os.environ.get("LABEL_STUDIO_PORT", "8080")
        sys.argv += ["start", "--port", port]
    sys.exit(main())
