"""
Installerer portabilitetsvakten (sitecustomize.py) i .pyruntime.

.pyruntime er gitignorert (stor binaerruntime som kopieres MED nav-mappa,
ikke via git), saa selve vaktfila ligger ikke i git. Denne kopien i
portabilitet/ ER sporet, og skriptet legger den paa plass. Kjores etter
en ev. gjenoppbygging av runtimen:

    python portabilitet/installer_portabilitetsvakt.py
"""
import os
import shutil

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KILDE = os.path.join(ROT, "portabilitet", "sitecustomize.py")
MAAL = os.path.join(ROT, ".pyruntime", "Lib", "site-packages",
                    "sitecustomize.py")

if not os.path.isfile(KILDE):
    raise SystemExit(f"Fant ikke kilden: {KILDE}")
if not os.path.isdir(os.path.dirname(MAAL)):
    raise SystemExit(f"Fant ikke .pyruntime — er den bygget? ({os.path.dirname(MAAL)})")

shutil.copyfile(KILDE, MAAL)
print(f"Portabilitetsvakt installert: {MAAL}")
