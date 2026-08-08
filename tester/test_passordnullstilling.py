"""Bytt passord fra kontrollpanelet — trygt (R176, R178).

Et glemt passord er den eneste feilen i Label Studio som ikke er et
driftsproblem, men et menneske som står låst ute. Verktøyet fantes, men
lå i et skript ingen finner.

FØRSTE VERSJON SENDTE BRUKEREN TIL ET KONSOLLVINDU
Det var trygt, men feil for formålet: en ansatt som har glemt passordet
sitt skal ikke måtte forholde seg til en svart rute. Dialogen tar seg
av HELE jobben nå — konto, nytt passord, bekreftelse.

DA MÅ HEMMELIGHETEN HÅNDTERES DER DEN ER
  * feltene er maskerte (`show="•"`)
  * verdien leses RETT fra widgeten, ikke gjennom en `StringVar` —
    den ville lagt den i Tcl-tolkerens variabeltabell, der vi ikke kan
    slette den. Et felt kan vi tømme, og det gjør vi.
  * den sendes videre i en PIPE (stdin). Aldri som argument:
    `--password <verdi>` ville stått i prosesslista, synlig for enhver
    som kjører `tasklist` mens kommandoen går, og i skallhistorikken.
  * ingen melding — heller ikke en feilmelding — inneholder den.

HVORFOR EN UNDERPROSESS I DET HELE TATT
Passordet må hashes med Djangos egen hasher for at Label Studio skal
godta det. Å laste Django inn i GUI-prosessen ville tatt sekunder og
kunne henge vinduet.

VAKTENE MÅLER KODE, IKKE TEKST
Seks ganger i denne gjennomgangen har en vakt slått ned på en KOMMENTAR
som forklarer hvorfor noe IKKE gjøres. `_bare_kode` fjerner kommentarer
og docstrings før noe måles.
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


def _bare_kode(tekst: str) -> str:
    """Kildeteksten UTEN kommentarer og docstrings.

    Fem ganger i denne gjennomgangen har en vakt slått ned på en
    KOMMENTAR som forklarer hvorfor noe IKKE gjøres — «--password»,
    «StringVar», «verdi». En vakt som roper på riktig kode blir slått
    av, ikke fikset, så den må måle det som kjøres."""
    uten_docstring = re.sub(r'"""(?:.|\n)*?"""', "", tekst)
    return "\n".join(l for l in uten_docstring.splitlines()
                     if not l.lstrip().startswith("#"))


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

def test_passordfeltene_er_maskerte(gui):
    """Dialogen HAR inndatafelt — det er hele poenget: en ansatt som
    har glemt passordet sitt skal slippe et konsollvindu. Men de må
    være maskerte."""
    kropp = _bare_kode(_metode(gui, "_nullstill_ls_passord"))
    assert kropp, "metoden mangler"
    assert 'show="•"' in kropp, "passordfeltet viser tegnene"


def test_passordet_ligger_ikke_i_en_tkinter_variabel(gui):
    """Verdien leses RETT fra widgeten med `.get()`. En `StringVar`
    ville lagt den i Tcl-tolkerens variabeltabell, der vi ikke kan
    slette den — et felt kan vi tømme."""
    kropp = _bare_kode(_metode(gui, "_nullstill_ls_passord"))
    # Én StringVar er lov: den holder VALGT KONTO, ikke passordet.
    assert kropp.count("StringVar") <= 1
    assert "textvariable" not in kropp, (
        "passordfeltet er bundet til en variabel vi ikke kan tømme")


def test_feltene_toemmes_etter_bruk(gui):
    kropp = _bare_kode(_metode(gui, "_nullstill_ls_passord"))
    assert "def _toem" in kropp and "delete(0, tk.END)" in kropp


def test_passordet_sendes_gjennom_en_PIPE_ikke_som_argument(gui):
    """`--password <verdi>` ville stått i prosesslista, synlig for
    enhver som kjører `tasklist` mens kommandoen går — og i
    skallhistorikken. En pipe har ingen av delene."""
    kropp = _bare_kode(_metode(gui, "_skriv_ls_passord"))
    assert kropp, "sendemetoden mangler"
    assert "input=passord" in kropp, "passordet sendes ikke på stdin"
    assert "--password" not in kropp
    args = re.search(r"\[str\(PROSJEKT_ROT.*?e_post\]", kropp, re.S)
    assert args, "fant ikke argumentlista"
    assert "passord" not in args.group(0).lower()


def test_ingen_konsollvindu_blinker_opp(gui):
    """Dialogen ER poenget — et konsoll som glimter forbi ville sett ut
    som en feil."""
    kropp = _bare_kode(_metode(gui, "_skriv_ls_passord"))
    assert "CREATE_NO_WINDOW" in kropp


def test_svaret_plukkes_paa_merket_ikke_fra_stderr(gui):
    """Stderr er ikke vår alene: «RequestsDependencyWarning: urllib3 …»
    var det FØRSTE feildialogen viste, mens den ekte grunnen lå under
    (R178)."""
    kropp = _bare_kode(_metode(gui, "_skriv_ls_passord"))
    assert 'startswith("SVAR: ")' in kropp


def test_brukerlista_leses_KUN_lesende(gui):
    """Panelet skal aldri kunne skrive i Label Studio-basen."""
    kropp = _bare_kode(_metode(gui, "_ls_brukere"))
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
    kode = _bare_kode(skript)
    assert '"reset_password", "--username"' in kode
    assert "--password" not in kode


def test_settemodulen_leser_fra_stdin_og_merker_svaret():
    """Den nye veien: passordet kommer på stdin, svaret går på stdout
    med et fast merke, og passordet står aldri i noen av dem."""
    kilde = io.open(os.path.join(ROT, "skript", "sett_ls_passord.py"),
                    encoding="utf-8").read()
    kode = _bare_kode(kilde)
    assert "sys.stdin.readline()" in kode
    assert 'SVARMERKE = "SVAR: "' in kode
    assert "--password" not in kode
    for linje in kode.splitlines():
        s = linje.strip()
        if s.startswith("print("):
            uten = re.sub(r'"[^"]*"|\'[^\']*\'', "", s)
            assert "passord" not in uten.lower(), s


def test_settemodulen_setter_soekestien_for_django():
    """Label Studios innstillinger importerer `core.…` som en
    TOPPNIVÅ-pakke. Uten pakkemappa på sys.path gir django.setup()
    «No module named core» — en feil som ser ut som en manglende
    installasjon, men bare er feil søkesti (R178)."""
    kilde = io.open(os.path.join(ROT, "skript", "sett_ls_passord.py"),
                    encoding="utf-8").read()
    assert "label_studio.__path__[0]" in kilde
    assert '"core.settings.label_studio"' in kilde


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

_MAALT = {}


def _maal_kolonner():
    """(kolonner, ekstra, hoyder) — x per rad, og hoyden per knapp.

    MÅLES ÉN GANG og bufres. Første versjon bygget et nytt Tk-vindu
    per test, og da hendte det at ett av dem ikke fikk laget rota —
    testen hoppet over med «ingen skjerm tilgjengelig». Et hopp som
    kommer og går er verre enn et fast: kjøringen ser grønn ut, og
    ingen legger merke til at vakten ikke målte noe den gangen."""
    if _MAALT:
        return _MAALT["kolonner"], _MAALT["ekstra"], _MAALT["hoyder"]
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
        kolonner, ekstra, hoyder = {}, {}, {}
        for tj in g.KONTROLL_TJENESTER:
            rad = f._kort[tj["key"]]["rad"]
            for barn in rad.winfo_children():
                for b in [barn] + list(barn.winfo_children()):
                    if isinstance(b, tk.Button):
                        x, navn = b.winfo_rootx(), b.cget("text")
                        hoyder.setdefault(navn, set()).add(b.winfo_height())
                        if navn == "Passord":
                            ekstra[tj["key"]] = x
                        else:
                            kolonner.setdefault(navn, set()).add(x)
        _MAALT.update(kolonner=kolonner, ekstra=ekstra, hoyder=hoyder)
        return kolonner, ekstra, hoyder
    finally:
        rot.destroy()


def test_de_fire_faste_knappene_staar_i_samme_kolonne():
    """Selve målingen — ikke en vurdering av hvordan koden ser ut."""
    kolonner, _, _h = _maal_kolonner()
    assert kolonner, "fant ingen knapper å måle"
    skjeve = {t: sorted(v) for t, v in kolonner.items() if len(v) > 1}
    assert not skjeve, (
        f"disse knappene står ikke på linje på tvers av radene: {skjeve}")


def test_passordknappen_staar_TIL_HOYRE_for_de_faste():
    """Den gjør noe annet enn de fire — de styrer TJENESTEN, denne
    gjelder en BRUKER — og avstanden sier det uten at noe forklares."""
    kolonner, ekstra, _h = _maal_kolonner()
    assert "label_studio" in ekstra, "passordknappen ble ikke funnet"
    lengst_til_hoyre = max(max(v) for v in kolonner.values())
    assert ekstra["label_studio"] > lengst_til_hoyre


def test_bare_label_studio_har_ekstraknappen():
    _, ekstra, _h = _maal_kolonner()
    assert set(ekstra) == {"label_studio"}


def test_alle_fem_knappene_er_like_hoye():
    """Passordknappen ble først pakket med `fill="both"` og strakk seg
    over hele rammehøyden — synlig større enn de andre. Plassen var
    reservert for å få ting på linje, og gjorde det motsatte.

    Målingen avdekket også en eldre skjevhet: Start/Stopp hadde
    `pady=3` mens `tema_knapp` bruker 4, altså to piksler lavere enn
    Åpne/Logg. Med fire knapper så ingen det; med fem ble det synlig
    (R177)."""
    _k, _e, hoyder = _maal_kolonner()
    assert hoyder, "fant ingen knapper å måle"
    alle = {h for v in hoyder.values() for h in v}
    assert len(alle) == 1, (
        f"knappene har ulik høyde: "
        f"{ {n: sorted(v) for n, v in hoyder.items()} }")
