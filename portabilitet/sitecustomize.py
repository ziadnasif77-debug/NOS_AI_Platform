"""
NAV — portabilitetsvakt. Kjøres AUTOMATISK av Python ved oppstart (site
importerer sitecustomize hvis den finnes på sys.path).

Formål: prosjekt-tolken (.pyruntime) skal ALDRI hente pakker fra
C:\\Users\\...\\AppData (user-site). Uten dette havner den katalogen på
sys.path FØR nav sine egne pakker når ENABLE_USER_SITE er på, og da
lastes torch/PIL/transformers m.fl. fra C: — som IKKE følger med når
nav-mappa kopieres til en server. Da starter ikke tjenesten.

Launcherne setter PYTHONNOUSERSITE=1, men det er skjørt: kjører noen
python direkte, eller glemmer én .bat variabelen, lekker C: inn igjen.
Denne fila fjerner user-site uansett hvordan tolken startes — vernet
bor i selve runtimen, ikke i hver launcher.

Rører KUN denne tolken (.pyruntime). Andre Python-installasjoner på
maskinen påvirkes ikke, siden fila ligger under .pyruntime.
"""
import os
import sys

try:
    import site

    _bruker = ""
    try:
        _bruker = os.path.normcase(site.getusersitepackages() or "")
    except Exception:
        pass

    if _bruker:
        # Alt under brukerens AppData\Roaming\Python fjernes fra sys.path
        beholdt = []
        for p in sys.path:
            n = os.path.normcase(p)
            if n == _bruker or n.startswith(_bruker + os.sep):
                continue
            beholdt.append(p)
        sys.path[:] = beholdt

    # Slå av mekanismen helt, så senere kode ikke legger den til igjen
    site.ENABLE_USER_SITE = False
except Exception:
    # En portabilitetsvakt skal ALDRI hindre tolken i å starte
    pass

# --- Cache-/modellstier inn i nav-mappa ---------------------------------
# Uten disse cacher torch/transformers/easyocr til C:\Users\...\.cache, og
# nedlastede modeller følger IKKE med når nav-mappa kopieres — første kall
# på en offline server ville da forsøkt å laste ned og feilet. Launcherne
# setter noen av dem, men ikke alle overalt. Her settes de FRA nav-roten
# uansett hvordan tolken startes. setdefault: en launcher (eller bruker)
# kan fortsatt overstyre bevisst.
try:
    # nav-roten = tre nivåer opp fra .pyruntime\Lib\site-packages
    _rot = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

    def _sett(navn, *deler):
        sti = os.path.join(_rot, *deler)
        os.environ.setdefault(navn, sti)

    _sett("HF_HOME", ".cache", "huggingface")
    _sett("TRANSFORMERS_CACHE", ".cache", "huggingface")
    _sett("HUGGINGFACE_HUB_CACHE", ".cache", "huggingface", "hub")
    _sett("TORCH_HOME", ".cache", "torch")
    _sett("XDG_CACHE_HOME", ".cache")
    _sett("EASYOCR_MODULE_PATH", ".EasyOCR")
    _sett("PIP_CACHE_DIR", ".cache", "pip")
    # MERK: HF_HUB_OFFLINE settes IKKE her. Det ville brutt
    # last_ned_modeller.py (som BEVISST henter modeller fra nettet). Drift
    # trenger det ikke uansett — serveren laster modeller fra lokale
    # stier (NORHAND_STI/BOREALIS_STI), ikke fra hub-en.
except Exception:
    pass
