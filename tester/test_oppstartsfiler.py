"""
Vakt for oppstartsfilene (.bat/.vbs).

Bakgrunnen er en ekte, innsjekket feil: `start_api_med_vakthund.bat`
kalte `skript<VT>akthund.py` fordi «\\v» i «skript\\vakthund.py» ble
tolket som escape-sekvensen vertikal tabulator da fila ble skrevet fra
en Python-streng. Stien finnes ikke, så VAKTHUNDEN STARTET ALDRI fra
den dokumenterte veien — og vakthunden er nettopp det som skulle fange
at API-et dør av seg selv. Feilen var usynlig: byte 11 vises ikke i en
editor, .bat-en så riktig ut, og cmd sa bare at fila ikke fantes.

Samme klasse feil rammer `\\n`, `\\t`, `\\r`, `\\b`, `\\f`, `\\a` — og
alle vanlige norske stier i dette prosjektet begynner med `data\\…`,
`skript\\…`, `delt\\…`, `tester\\…`. Denne testen leser RÅ BYTES, for
det er den eneste måten å se forskjell på.

I tillegg: en .bat med bare LF brekker under cmd.exe. `.gitattributes`
sier `eol=crlf`, men attributtet virker først ved utsjekk — en fil
skrevet direkte av et verktøy kan fortsatt bli LF.
"""
import os

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Alt som kan komme av en escape-sekvens tolket ved en feil. TAB (9),
# LF (10) og CR (13) er lovlige tegn i en tekstfil og holdes utenfor.
KONTROLLTEGN = {i: navn for i, navn in {
    7: "\\a (bjelle)", 8: "\\b (rygg)", 11: "\\v (vertikal tabulator)",
    12: "\\f (sideskift)", 0: "NUL",
}.items()}


def _oppstartsfiler():
    """Alle .bat- og .vbs-filer i prosjektet, uten de gitignorerte
    mappene (.pyruntime, .venv-prefect) som ikke er våre."""
    ut = []
    for mappe, undermapper, filer in os.walk(ROT):
        undermapper[:] = [d for d in undermapper
                          if not d.startswith((".", "__"))
                          and d not in ("node_modules", "data")]
        for navn in filer:
            if navn.lower().endswith((".bat", ".vbs")):
                ut.append(os.path.join(mappe, navn))
    return sorted(ut)


def test_finnes_oppstartsfiler_i_det_hele_tatt():
    """Uten denne ville de andre testene vært grønne på en tom liste."""
    filer = _oppstartsfiler()
    assert len(filer) >= 10, f"fant bare {len(filer)} oppstartsfiler"


def test_ingen_kontrolltegn_fra_feiltolket_escape():
    """Den ekte feilen: byte 11 midt i «skript\\vakthund.py»."""
    funn = []
    for sti in _oppstartsfiler():
        with open(sti, "rb") as f:
            raa = f.read()
        for byte, navn in KONTROLLTEGN.items():
            if bytes([byte]) in raa:
                linje = 1 + raa[:raa.index(bytes([byte]))].count(b"\n")
                funn.append(f"{os.path.relpath(sti, ROT)}:{linje} "
                            f"har byte {byte} — ser ut som {navn} tolket "
                            f"som escape i stedet for omvendt skråstrek "
                            f"+ bokstav")
    assert not funn, "Kontrolltegn i oppstartsfiler:\n  " + "\n  ".join(funn)


def test_bat_filer_har_crlf():
    """cmd.exe krever CRLF. Bare LF gir «kommandoen ble ikke funnet» på
    linjer som ser helt riktige ut."""
    feil = []
    for sti in _oppstartsfiler():
        if not sti.lower().endswith(".bat"):
            continue
        with open(sti, "rb") as f:
            raa = f.read()
        bare_lf = raa.count(b"\n") - raa.count(b"\r\n")
        if bare_lf:
            feil.append(f"{os.path.relpath(sti, ROT)}: {bare_lf} linjer "
                        f"med bare LF")
    assert not feil, ("Disse .bat-filene brekker under cmd.exe:\n  "
                      + "\n  ".join(feil))


def test_alle_python_kall_i_bat_peker_paa_en_fil_som_finnes():
    """Fanger feilstavede og ødelagte stier direkte — uten å kjøre noe.

    Dette er den andre halvdelen av vakthund-feilen: selv om
    kontrolltegnet var borte, ville `skript\\vakthudn.py` gitt nøyaktig
    samme tause resultat."""
    import re
    mangler = []
    monster = re.compile(rb"%PY[W]?%\"?\s+(?:-m\s+\S+\s+)?"
                         rb"([\w\\/.-]+\.py)", re.IGNORECASE)
    for sti in _oppstartsfiler():
        if not sti.lower().endswith(".bat"):
            continue
        with open(sti, "rb") as f:
            raa = f.read()
        for treff in monster.finditer(raa):
            rel = treff.group(1).decode("utf-8", "replace").replace("\\", os.sep)
            if not os.path.exists(os.path.join(ROT, rel)):
                mangler.append(f"{os.path.relpath(sti, ROT)} kaller "
                               f"«{rel}» — finnes ikke")
    assert not mangler, ("Oppstartsfiler peker på Python-filer som ikke "
                         "finnes:\n  " + "\n  ".join(mangler))


# ------------------------------------------------------------------ #
#  Oppstart ved maskinstart går gjennom VAKTHUNDEN (R142)             #
# ------------------------------------------------------------------ #

TJENESTEBAT = os.path.join(ROT, "skript", "tjeneste",
                           "kjor_dokument_api.bat")


def _tjenesteteksten():
    with open(TJENESTEBAT, encoding="utf-8") as f:
        return f.read()


def test_tjenesten_starter_VAKTHUNDEN_ikke_serveren_direkte():
    """Målt: ingenting fra prosjektet startet ved maskinoppstart — ingen
    tjeneste, ingen planlagt oppgave, ingen oppstartsmappe, ingen
    Run-nøkkel. Og da mekanismen fantes, startet den `dokument_api.py`
    RETT, altså utenom vakthunden.

    Det er ikke et detaljvalg. Oppgaveplanleggeren restarter bare en
    prosess som HAR AVSLUTTET; en HENGT server lever videre og blir
    stående. Vakthunden helsesjekker `/hjelp` og restarter også da
    (R123) — «en hengt prosess er like ubrukelig som en død» — og den
    skriver EXITKODEN, som er det som manglet i to døgn (R122)."""
    tekst = _tjenesteteksten()
    kode = "\n".join(l for l in tekst.splitlines()
                     if not l.strip().upper().startswith("REM"))
    assert "vakthund.py" in kode, (
        "tjenesteveien starter ikke vakthunden — da er oppstart ved "
        "maskinstart uten helsesjekk og uten exitkode i loggen")
    assert "dokument_api.py" not in kode, (
        "tjenesteveien starter serveren direkte, utenom vakthunden")


def test_tjenesteveien_VENTER_paa_laasen_i_stedet_for_aa_avslutte():
    """R141 ga vakthunden en enkeltinstanslås. Rakk panelet å starte sin
    vakthund først, ville tjenestens avsluttet med 0 — og
    Oppgaveplanleggeren regnet oppgaven som FERDIG. Lukket brukeren så
    panelet, sto serveren uten tilsyn til neste omstart."""
    kode = "\n".join(l for l in _tjenesteteksten().splitlines()
                     if not l.strip().upper().startswith("REM"))
    assert "--vent" in kode


def test_vakthunden_forstaar_vent():
    kilde = open(os.path.join(ROT, "skript", "vakthund.py"),
                 encoding="utf-8").read()
    kode = "\n".join(l.split("#")[0] for l in kilde.splitlines())
    assert '"--vent" in sys.argv' in kode
    # og den skal VENTE, ikke avslutte
    etter = kode[kode.index('"--vent" in sys.argv'):]
    assert "while _laas is None" in etter[:900]


def test_tjenestebaten_holder_alt_i_nav_mappa():
    """CLAUDE.md §1: oppgaven kjøres som SYSTEM, som ikke arver
    brukerens miljø. Da må .bat-en peke cache og modeller inn i nav
    selv, ellers havner de i SYSTEM-kontoens profil på C."""
    tekst = _tjenesteteksten()
    for navn in ("EASYOCR_MODULE_PATH", "HF_HOME", "PIP_CACHE_DIR",
                 "PYTHONNOUSERSITE"):
        assert navn in tekst, f"{navn} settes ikke i tjeneste-baten"
    assert "%CD%" in tekst, "stiene er ikke avledet fra prosjektroten"
