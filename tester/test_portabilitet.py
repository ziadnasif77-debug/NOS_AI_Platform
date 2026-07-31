"""
Portabilitetsvakt: nav-mappa skal kunne KOPIERES til en annen maskin
(eller et annet stasjonsbokstav) og virke uten at noe hentes fra C:.

Disse testene fanger regresjoner der en pakke, cache eller sti smyger
seg tilbake til brukerprofilen på C: — noe som IKKE følger med en
mappekopi, og som ville hindret tjenesten i å starte på en server.

Kjøres med prosjekt-tolken (.pyruntime), som via sitecustomize.py slår
av user-site og peker cachene inn i nav.
"""
import os
import sys

sys.path.insert(0, ".")

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _under_nav(sti: str) -> bool:
    return os.path.normcase(os.path.abspath(sti)).startswith(
        os.path.normcase(ROT))


# ---------- sys.path ----------
def test_ingen_brukerprofil_paa_sys_path():
    """AppData\\Roaming\\Python (user-site) skal ALDRI ligge på sys.path —
    da lastes pakker fra C: og følger ikke med en kopi."""
    lekk = [p for p in sys.path
            if p and ("appdata" in p.lower()
                      or (os.path.normcase(p).startswith("c:")
                          and "roaming" in p.lower()))]
    assert lekk == [], f"user-site lekket inn: {lekk}"


def test_user_site_er_avslaatt():
    import site
    assert site.ENABLE_USER_SITE is False


# ---------- kritiske pakker løses fra nav ----------
def test_alle_driftspakker_lastes_fra_nav():
    """Pakkene serveren faktisk bruker skal ligge under nav-mappa."""
    import importlib.util as u
    feil = {}
    for navn in ("torch", "PIL", "transformers", "llama_cpp", "cv2",
                 "requests", "easyocr", "pyzbar", "fitz", "numpy", "rapidocr"):
        try:
            spec = u.find_spec(navn)
        except Exception as exc:      # noqa: BLE001 — vil vite HVILKEN
            feil[navn] = f"find_spec feilet: {exc}"
            continue
        if spec is None:
            feil[navn] = "MANGLER"
            continue
        sti = spec.origin or (spec.submodule_search_locations[0]
                              if spec.submodule_search_locations else "")
        if not _under_nav(sti):
            feil[navn] = sti
    assert feil == {}, f"pakker lastet UTENFOR nav: {feil}"


# ---------- cache-/modellstier peker inn i nav ----------
def test_cache_stier_peker_inn_i_nav():
    """Modeller/cacher torch/transformers/easyocr laster ned til skal
    ligge i nav, ellers følger de ikke med en kopi."""
    for var in ("HF_HOME", "TRANSFORMERS_CACHE", "TORCH_HOME",
                "EASYOCR_MODULE_PATH", "XDG_CACHE_HOME"):
        verdi = os.environ.get(var)
        assert verdi, f"{var} er ikke satt"
        assert _under_nav(verdi), f"{var} peker utenfor nav: {verdi}"


def test_sitecustomize_paatvinger_ikke_offline():
    """sitecustomize skal IKKE sette HF_HUB_OFFLINE — det ville brutt
    last_ned_modeller.py. Vi verifiserer kildekoden direkte, så en
    operatør fortsatt kan sette den bevisst i miljøet uten at testen
    feiler på det."""
    sc = os.path.join(ROT, ".pyruntime", "Lib", "site-packages",
                      "sitecustomize.py")
    if not os.path.isfile(sc):
        return                         # ingen vakt-fil å sjekke
    with open(sc, encoding="utf-8") as f:
        kildekode = f.read()
    # ingen linje som SETTER offline-flaggene (kommentar om dem er greit)
    for linje in kildekode.splitlines():
        kode = linje.split("#", 1)[0]
        assert "HF_HUB_OFFLINE" not in kode or "setdefault" not in kode
        assert "TRANSFORMERS_OFFLINE" not in kode or "setdefault" not in kode


# ---------- ingen hardkodet C: i driftskoden ----------
def test_ingen_hardkodet_c_sti_i_driftskoden():
    """delt/ og de importerte skriptene skal ikke ha en hardkodet
    C:\\-sti i en kodelinje (kommentarer/strenger til feilmeldinger er
    greit; her ser vi etter faktiske stier i tilordninger)."""
    import glob
    import re
    mistenkt = []
    filer = glob.glob(os.path.join(ROT, "delt", "*.py"))
    filer += [os.path.join(ROT, "skript", "dokument_api.py")]
    # r"C:\..." eller "C:/..." brukt i en tilordning/kall, ikke i kommentar
    monster = re.compile(r'(?<![#])\b[Cc]:[\\/](?:Users|Windows|AppData)',
                         re.IGNORECASE)
    for f in filer:
        with open(f, encoding="utf-8") as fh:
            for nr, linje in enumerate(fh, 1):
                strippet = linje.split("#", 1)[0]   # dropp kommentar
                if monster.search(strippet):
                    mistenkt.append(f"{os.path.basename(f)}:{nr}")
    assert mistenkt == [], f"hardkodet C:-sti i driftskode: {mistenkt}"
