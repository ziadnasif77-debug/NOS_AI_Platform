"""Et navn som brukes, skal være bundet et sted koden kan se det.

R182: `_do_post_intern` sendte `skanning_kjorte` til `svar_paa_sporsmal`.
Navnet finnes — som lokal variabel i `_les_dokument`, en helt annen
metode. Python oppdager ikke det ved import; det smeller først når
linja kjøres. Og linja lå på POST /spor med fil og spørsmål, altså
hovedveien inn i ruta:

    NameError: name 'skanning_kjorte' is not defined   →   500

1590 tester var grønne mens ruta var død. Ingen av dem kjørte akkurat
den grenen — og en NameError trenger ingen spesiell inndata for å
utløses, bare at linja i det hele tatt blir nådd én gang.

Derfor denne vakten: den leser SYNTAKSTREET og finner navn som ikke
bindes noe sted i rekkevidde — ikke parameter, ikke tilordnet, ikke på
modulnivå, ikke innebygd, ikke bundet i en omsluttende funksjon eller
lambda. Da trengs ingen test som «tilfeldigvis» går innom linja.

VAKTEN ER MÅLT, IKKE ANTATT
Den første versjonen fant IKKE R182. Modulnivå-settet ble regnet ut med
`ast.walk` over hele treet, så enhver lokal variabel hvor som helst i
fila telte som «global» — og da er ingenting udefinert. En vakt som
alltid er grønn er verre enn ingen vakt: den ble kjørt mot den ekte
feilen først, og skrev ut nettopp den linja, før den fikk stå.

Motprøven er kjørt like nøye: hele `skript/`, `delt/`, `tester/` og
`nav_klient.py` gir NULL funn. Lambda-parametre og lukninger over `self`
ga falske treff i mellomversjonene — begge deler er lovlig kode, og en
vakt som roper på lovlig kode blir slått av (R180).
"""
import ast
import builtins
import os
import sys

sys.path.insert(0, ".")

# Navn som alltid finnes uten å være tilordnet i fila.
INNEBYGDE = set(dir(builtins)) | {"__file__", "__name__", "__doc__",
                                  "__package__", "__spec__", "__builtins__"}
FUNKSJON = (ast.FunctionDef, ast.AsyncFunctionDef)
# Alt som åpner et EGET navnerom. Lambda hører med: parametrene dens er
# ikke synlige utenfor, og navnene i kroppen skal ikke tilskrives den
# omsluttende funksjonen.
EGET_ROM = (*FUNKSJON, ast.ClassDef, ast.Lambda)

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAPPER = ("skript", "delt", "tester", "portabilitet")


def _bundet_her(kropp) -> set:
    """Navn som bindes i DENNE kroppen — uten å gå inn i nestede rom."""
    ut, stabel = set(), list(kropp)
    while stabel:
        n = stabel.pop()
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            ut.add(n.id)
        elif isinstance(n, EGET_ROM):
            if not isinstance(n, ast.Lambda):
                ut.add(n.name)     # def-en selv er bundet her
            continue               # …men innmaten er et annet rom
        elif isinstance(n, ast.ExceptHandler) and n.name:
            ut.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for alias in n.names:
                ut.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            ut.update(n.names)
        stabel.extend(ast.iter_child_nodes(n))
    return ut


def _parametre(fn) -> set:
    a = fn.args
    navn = {p.arg for p in a.args + a.posonlyargs + a.kwonlyargs}
    if a.vararg:
        navn.add(a.vararg.arg)
    if a.kwarg:
        navn.add(a.kwarg.arg)
    return navn


def _brukt_her(kropp) -> list:
    """Navn som LESES i denne kroppen — uten nestede rom."""
    ut, stabel = [], list(kropp)
    while stabel:
        n = stabel.pop()
        if isinstance(n, EGET_ROM):
            continue
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            ut.append((n.lineno, n.id))
        stabel.extend(ast.iter_child_nodes(n))
    return ut


def _gaa_inn(fn, ytre: set, funn: list) -> None:
    kropp = fn.body if isinstance(fn.body, list) else [fn.body]
    kjent = ytre | _parametre(fn) | _bundet_her(kropp)
    navn_paa_fn = getattr(fn, "name", "<lambda>")
    for linje, navn in _brukt_her(kropp):
        if navn not in kjent:
            funn.append((linje, navn_paa_fn, navn))
    # Nestede funksjoner og lambdaer ser det ytre rommet — derfor `kjent`.
    for n in ast.walk(fn):
        if isinstance(n, (*FUNKSJON, ast.Lambda)) and n is not fn:
            _gaa_inn(n, kjent, funn)


def udefinerte_navn(kildekode: str) -> list:
    """[(linje, funksjon, navn)] for navn uten binding i rekkevidde."""
    tre = ast.parse(kildekode)
    globale = _bundet_her(tre.body) | INNEBYGDE
    funn = []
    for n in tre.body:
        if isinstance(n, FUNKSJON):
            _gaa_inn(n, globale, funn)
        elif isinstance(n, ast.ClassDef):
            # Klassekroppen er et eget rom, men metodene ser IKKE inn i
            # det — de ser modulnivå. Klassevariabler nås via self/klassen.
            for m in n.body:
                if isinstance(m, FUNKSJON):
                    _gaa_inn(m, globale, funn)
    return funn


def _kildefiler():
    for mappe in MAPPER:
        bane = os.path.join(ROT, mappe)
        if not os.path.isdir(bane):
            continue
        for navn in sorted(os.listdir(bane)):
            if navn.endswith(".py"):
                yield os.path.join(bane, navn)
    yield os.path.join(ROT, "nav_klient.py")


def test_ingen_udefinerte_navn_i_prosjektet():
    feil = []
    for sti in _kildefiler():
        if not os.path.isfile(sti):
            continue
        with open(sti, encoding="utf-8") as f:
            kilde = f.read()
        for linje, fn, navn in udefinerte_navn(kilde):
            feil.append(f"{os.path.relpath(sti, ROT)}:{linje}: {navn!r} "
                        f"i {fn}() bindes ingen steder i rekkevidde")
    assert not feil, ("Navn uten binding — dette blir NameError (500) "
                      "første gang linja kjøres:\n  " + "\n  ".join(feil))


# ------------------------------------------------------------------ #
#  Vakten skal FAKTISK se feilen den finnes for                        #
# ------------------------------------------------------------------ #

FEILEN_FRA_R182 = '''
def svar_paa_sporsmal(tekst, sporsmal, ocr, hand, koder, lest=True):
    return {}


class Handler:
    def _les_dokument(self, les_strekkoder, slag):
        skanning_kjorte = bool(les_strekkoder) and slag != "tekst"
        return skanning_kjorte

    def _do_post_intern(self):
        return svar_paa_sporsmal("tekst", "sporsmal", False, [], [],
                                 skanning_kjorte)
'''


def test_vakten_ser_den_ekte_feilen():
    """Uten denne ville en vakt som ALLTID er grønn sett like bra ut.
    Første utgave var nettopp det, og ble byttet ut (se modul-docstringen)."""
    funn = udefinerte_navn(FEILEN_FRA_R182)
    assert [(f, n) for _, f, n in funn] == [
        ("_do_post_intern", "skanning_kjorte")]


def test_lovlig_kode_gir_ingen_falske_treff():
    """Lukning over `self`, lambda-parametre, nestede def-er,
    except-navn og comprehension-variabler er alle lovlige."""
    lovlig = '''
import os

TABELL = {}

class Klient:
    def send(self, filer, tilbakekall):
        resultat = [os.path.basename(f) for f in filer]

        def arbeider(indeks):
            self.logg(resultat[indeks])          # lukning over self

        try:
            arbeider(0)
        except OSError as feil:
            self.logg(str(feil))
        return lambda data, brukt: tilbakekall(self, data, brukt, TABELL)
'''
    assert udefinerte_navn(lovlig) == []
