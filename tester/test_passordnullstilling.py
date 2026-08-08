"""Passordet skal ALDRI gå gjennom kontrollpanelet (R176).

En glemt passord er den eneste feilen i Label Studio som ikke er et
driftsproblem, men et menneske som står låst ute. Verktøyet fantes, men
lå i et skript ingen finner — så knappen hører hjemme ved siden av
tjenesten den gjelder.

SKILLET SOM ER HELE POENGET
Panelet gjør HVEM-delen: leser brukerlista fra basen og lar deg velge.
Selve HEMMELIGHETEN skrives i et eget konsollvindu, rett til Label
Studios egen `reset_password`, som spør med `getpass`.

Et passordfelt i GUI-et ville lagt hemmeligheten i denne prosessens
minne, i Tkinters strengvariabler, og potensielt i en feilmelding — og
GUI-et er nettopp den delen som logger mest. Konsollveien har ingen av
delene.

OG ALDRI VIA KOMMANDOLINJA
`--password <verdi>` ville lagt passordet i skallhistorikken og i
prosesslista, synlig for enhver som kjører `tasklist`. Skriptet setter
derfor `sys.argv` UTEN passord og lar Label Studio spørre selv.
"""
import ast
import io
import os
import re
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI_STI = os.path.join(ROT, "skript", "api_klient_gui.py")
SKRIPT_STI = os.path.join(ROT, "skript", "nullstill_ls_passord.py")


@pytest.fixture(scope="module")
def gui():
    return io.open(GUI_STI, encoding="utf-8").read()


@pytest.fixture(scope="module")
def skript():
    return io.open(SKRIPT_STI, encoding="utf-8").read()


def _metode(kilde: str, navn: str) -> str:
    """Kildeteksten til én metode, uten å importere Tkinter."""
    tre = ast.parse(kilde)
    for node in ast.walk(tre):
        if isinstance(node, ast.FunctionDef) and node.name == navn:
            return ast.get_source_segment(kilde, node) or ""
    return ""


# ------------------------------------------------------------------ #
#  Knappen finnes, og er koblet                                        #
# ------------------------------------------------------------------ #

def test_knappen_finnes_paa_label_studio_kortet(gui):
    assert '"Passord"' in gui
    assert "_nullstill_ls_passord" in gui


def test_knappen_vises_BARE_for_label_studio(gui):
    """En passordknapp på API-kortet eller tunnelen ville vært
    meningsløs — de har ingen brukerkontoer."""
    assert 'if tjeneste["key"] == "label_studio":' in gui


def test_metodene_finnes(gui):
    assert _metode(gui, "_nullstill_ls_passord")
    assert _metode(gui, "_ls_brukere")


# ------------------------------------------------------------------ #
#  Kjernen: hemmeligheten passerer ikke panelet                        #
# ------------------------------------------------------------------ #

def test_panelet_har_ingen_passordvariabel(gui):
    """Ordet skal ikke finnes som et FELT i panelet — bare i tekst til
    brukeren og i navnet på knappen/metoden."""
    kropp = _metode(gui, "_nullstill_ls_passord")
    assert kropp, "metoden mangler"
    # Ingen Tkinter-variabel eller inndatafelt for et passord
    for mistenkt in ("StringVar", "tk.Entry", "ttk.Entry", 'show="•"',
                     'show="*"'):
        assert mistenkt not in kropp, (
            f"panelet lager et inndatafelt for passordet: {mistenkt}")


def test_passordet_sendes_ikke_som_argument(gui):
    """Det ville lagt det i prosesslista, synlig for `tasklist`."""
    kropp = _metode(gui, "_nullstill_ls_passord")
    assert "--password" not in kropp
    # Popen-kallet skal bare bære skriptet og BRUKERNAVNET
    popen = re.search(r"subprocess\.Popen\((.*?)\)\n", kropp, re.S)
    assert popen, "fant ikke Popen-kallet"
    assert "passord" not in popen.group(1).lower()


def test_eget_konsollvindu_apnes(gui):
    """Uten et eget vindu ville getpass-spørsmålet havnet i et skjult
    konsoll som ingen ser — og brukeren ville trodd at ingenting skjedde."""
    kropp = _metode(gui, "_nullstill_ls_passord")
    assert "CREATE_NEW_CONSOLE" in kropp


def test_brukerlista_leses_KUN_lesende(gui):
    """Panelet skal aldri kunne skrive i Label Studio-basen."""
    kropp = _metode(gui, "_ls_brukere")
    assert "mode=ro" in kropp, "basen åpnes ikke skrivebeskyttet"
    for farlig in ("UPDATE ", "DELETE ", "INSERT ", "DROP "):
        assert farlig not in kropp.upper()


# ------------------------------------------------------------------ #
#  Skriptet under: samme regel                                         #
# ------------------------------------------------------------------ #

def test_skriptet_sender_ikke_passord_paa_kommandolinja(skript):
    """`sys.argv` settes UTEN passord, så Label Studio spør selv med
    getpass. Med `--password` ville verdien havnet i skallhistorikken.

    Målt på KODEN, ikke på teksten: `--password` står i en kommentar som
    forklarer nettopp hvorfor den er utelatt, og et rått søk slo ned på
    den forklaringen. En vakt som roper på riktig kode blir slått av,
    ikke fikset — det er fjerde gang det mønsteret dukker opp i denne
    gjennomgangen."""
    kode = "\n".join(l for l in skript.splitlines()
                     if not l.lstrip().startswith("#"))
    assert '"reset_password", "--username"' in kode
    assert "--password" not in kode


def test_skriptet_peker_paa_RIKTIG_base(skript):
    """Uten LABEL_STUDIO_BASE_DATA_DIR bruker Label Studio
    standardkatalogen i brukerprofilen på C: — en helt annen, tom base.
    Kommandoen ville meldt «User not found», eller i verste fall endret
    passordet i feil base mens innlogging fortsatt feilet i den ekte."""
    assert "LABEL_STUDIO_BASE_DATA_DIR" in skript
    assert '"data", "label-studio"' in skript


def test_skriptet_skriver_aldri_ut_et_passord(skript):
    """Kildekontroll på utskriftene — samme regel som for
    nøkkelrotasjonen (R169)."""
    for linje in skript.splitlines():
        s = linje.strip()
        if not s.startswith("print("):
            continue
        uten_strenger = re.sub(r'"[^"]*"|\'[^\']*\'', "", s)
        assert "passord" not in uten_strenger.lower(), (
            f"et passord kan lekke ut i en utskrift: {s}")


# ------------------------------------------------------------------ #
#  Layoutet: én rad skal ikke skyve de andre ut av kolonnene (R177)   #
# ------------------------------------------------------------------ #
#
# Da Label Studio fikk en femte knapp, ble den raden bredere — og siden
# knapperaden er høyrestilt, skjøv den de fire faste knappene mot
# venstre. Kolonnene sluttet å stå under hverandre.
#
# Plassen reserveres derfor på ALLE rader, tom hos dem som ikke bruker
# den. Denne testen MÅLER posisjonene i stedet for å stole på at koden
# ser riktig ut.

def _maal_kolonner():
    """(kolonner, ekstraposisjon) — x for hver knapp, per rad."""
    tk = pytest.importorskip("tkinter")
    sys.path.insert(0, os.path.join(ROT, "skript"))
    import api_klient_gui as g

    try:
        rot = tk.Tk()
    except tk.TclError:
        pytest.skip("ingen skjerm tilgjengelig")
    rot.geometry("980x400")
    ramme = tk.Frame(rot)
    ramme.pack(fill="both", expand=True)

    class Fake:
        _kort = {}
        _bygg_kort = g.KontrollPanel._bygg_kort
        _start_tjeneste = _stopp_tjeneste = _aapne_tjeneste = _aapne_logg = \
            _nullstill_ls_passord = staticmethod(lambda *a, **k: None)

    f = Fake()
    try:
        for tj in g.KONTROLL_TJENESTER:
            f._bygg_kort(ramme, tj)
        rot.update()
        kolonner, ekstra = {}, {}
        for tj in g.KONTROLL_TJENESTER:
            rad = f._kort[tj["key"]]["rad"]
            for barn in rad.winfo_children():
                for b in [barn] + list(barn.winfo_children()):
                    if isinstance(b, tk.Button):
                        x = b.winfo_rootx()
                        if b.cget("text") == "Passord":
                            ekstra[tj["key"]] = x
                        else:
                            kolonner.setdefault(
                                b.cget("text"), set()).add(x)
        return kolonner, ekstra
    finally:
        rot.destroy()


def test_de_fire_faste_knappene_staar_i_samme_kolonne():
    """Selve målingen — ikke en vurdering av hvordan koden ser ut."""
    kolonner, _ = _maal_kolonner()
    assert kolonner, "fant ingen knapper å måle"
    skjeve = {t: sorted(v) for t, v in kolonner.items() if len(v) > 1}
    assert not skjeve, (
        f"disse knappene står ikke på linje på tvers av radene: {skjeve}")


def test_passordknappen_staar_TIL_HOYRE_for_de_faste():
    """Den gjør noe annet enn de fire — de styrer TJENESTEN, denne
    gjelder en BRUKER — og avstanden sier det uten at noe forklares."""
    kolonner, ekstra = _maal_kolonner()
    assert "label_studio" in ekstra, "passordknappen ble ikke funnet"
    lengst_til_hoyre = max(max(v) for v in kolonner.values())
    assert ekstra["label_studio"] > lengst_til_hoyre


def test_bare_label_studio_har_ekstraknappen():
    _, ekstra = _maal_kolonner()
    assert set(ekstra) == {"label_studio"}
