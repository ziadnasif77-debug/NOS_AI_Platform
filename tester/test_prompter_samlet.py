"""
Vakt for at ALL prompttekst blir liggende i `regler/prompter.md`.

Grunnen til at denne testen finnes: promptene lå spredt på seks steder i
`dokument_api.py` pluss en egen, eldre kopi i `spor_pdf.py`. Kopien
hadde sakket akterut — den manglet både tallregelen og sideregelen, så
samme dokument kunne få ulikt svar avhengig av hvilken vei det gikk.
Ingen merket det, fordi ingenting sa ifra.

Nå sier noe ifra.
"""
import ast
import os
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "skript"))

from delt import prompter  # noqa: E402


# ---------- 1) Kontrakten mellom kallstedene og fila ----------

# Hvert kallsted i koden, med feltene det sender. Legger du til et
# prompt-kall, føres det opp her — da fanger testen både at blokka
# finnes og at feltnavnene stemmer.
KALLSTEDER = [
    ("spor.dokumentsporsmal", {"egne_regler": "", "ocr_merknad": "",
                               "dokument": "DOK", "sporsmal": "SPM"}),
    ("spor.ocr_merknad", {}),
    ("spor.egne_regler_innledning", {}),
    ("spor.uten_dokument", {"sporsmal": "SPM"}),
    ("spor.sakssporsmal", {"dokumenter": "DOK", "sporsmal": "SPM"}),
    ("spor.normaliser_sporsmal", {"sporsmal": "SPM"}),
    ("korriger.forste_pass", {"usikre_blokk": "", "ocr_tekst": "OCR"}),
    ("korriger.usikre_overskrift", {}),
    ("korriger.selvkontroll", {"original": "A", "kandidat": "B"}),
    ("fyll_skjema.mal", {"dokument": "DOK", "grunnlag": "", "mal": "{}"}),
    ("fyll_skjema.paaminnelse", {}),
    ("fyll_skjema.belop_overskrift", {}),
    ("fyll_skjema.koder_overskrift", {}),
    ("fyll_skjema.datoer_overskrift", {}),
    ("fyll_skjema.identifikatorer_overskrift", {}),
    ("klassifiser.dokumenttype", {"dokument": "DOK",
                                  "koder": "faktura, vedtak, ukjent"}),
    ("oppsummer.instruks", {}),
    ("versjon", {}),
]


@pytest.mark.parametrize("navn,felter", KALLSTEDER,
                         ids=[n for n, _ in KALLSTEDER])
def test_hvert_kallsted_har_en_blokk_som_fylles_helt(navn, felter):
    tekst = prompter.hent(navn, **felter)
    assert tekst.strip(), f"«{navn}» er tom"
    assert "$" not in tekst, (
        f"«{navn}» har en plassholder igjen som ingen fylte ut — "
        f"modellen ville fått «$felt» rett i prompten")


def test_ingen_blokker_ligger_ubrukt_i_fila():
    """En blokk ingen kaller er en regel som ser ut til å gjelde, men
    ikke gjør det. Verre enn ingen regel."""
    ubrukt = prompter.blokknavn() - {n for n, _ in KALLSTEDER}
    assert not ubrukt, (
        f"Disse blokkene i regler/prompter.md brukes ikke av noe "
        f"kallsted: {sorted(ubrukt)}. Enten mangler kallet, eller så "
        f"skal blokka slettes.")


# ---------- 2) Prompttekst skal ikke krype tilbake i koden ----------

# Formuleringer som bare hører hjemme i en prompt. Tripwire, ikke bevis:
# den fanger det realistiske tilfellet — at noen limer en prompt inn i
# Python igjen — ikke enhver tenkelig omskriving.
PROMPTMARKORER = [
    "Svar KUN",
    "Du svarer på",
    "Du er en norsk assistent",
    "Du kvalitetssikrer",
    "Dokumentteksten er DATA",
    "Strenge regler",
    "Rett OCR-feil",
    "Rett KUN",
]

KODEMAPPER = ("skript", "delt")


def _tekstlige_konstanter(sti):
    """Strengliteraler i fila, UTEN docstrings og HTML. Docstrings er
    forklaringer til oss, ikke instruksjoner til modellen — og
    hjelpesidene er HTML."""
    tre = ast.parse(open(sti, encoding="utf-8").read())
    docstrings = set()
    for node in ast.walk(tre):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            forste = node.body[0] if node.body else None
            if (isinstance(forste, ast.Expr)
                    and isinstance(forste.value, ast.Constant)
                    and isinstance(forste.value.value, str)):
                docstrings.add(id(forste.value))
    for node in ast.walk(tre):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings
                and not ("<" in node.value and ">" in node.value)):
            yield node.lineno, node.value


def test_ingen_prompttekst_utenfor_regelfila():
    funn = []
    for mappe in KODEMAPPER:
        katalog = os.path.join(ROT, mappe)
        for fil in sorted(os.listdir(katalog)):
            if not fil.endswith(".py"):
                continue
            sti = os.path.join(katalog, fil)
            for linje, verdi in _tekstlige_konstanter(sti):
                for markor in PROMPTMARKORER:
                    if markor in verdi:
                        funn.append(f"{mappe}/{fil}:{linje} — «{markor}»")
    assert not funn, (
        "Prompttekst funnet i kode. Flytt den til regler/prompter.md og "
        "kall prompter.hent(...):\n  " + "\n  ".join(funn))


def test_markorene_finnes_fortsatt_i_regelfila():
    """Holder vakten over ærlig: skrives en prompt om slik at en markør
    forsvinner, slutter vakten å se etter noe som finnes — og da skal
    markørlista oppdateres, ikke ignoreres."""
    raa = open(prompter.PROMPTER_STI, encoding="utf-8-sig").read()
    borte = [m for m in PROMPTMARKORER if m not in raa]
    assert not borte, (
        f"Markørene {borte} finnes ikke lenger i regler/prompter.md. "
        f"Ble en prompt skrevet om? Oppdater PROMPTMARKORER her.")


# ---------- 3) Klippingen mot kontekstvinduet må fortsatt treffe ----------

def test_klippeankrene_finnes_i_promptene():
    """`_tilpass_kontekst` klipper DOKUMENTDELEN når prompten er for
    lang for kontekstvinduet, og finner den ved hjelp av faste ankre.
    Endres ordlyden rundt «Dokument:» eller «Spørsmål:», treffer ikke
    ankrene lenger — og da klippes prompten på midten i stedet, med
    spørsmålet i behold og halve dokumentet borte. Stille."""
    import dokument_api as api

    prompter_med_dokument = {
        "spor.dokumentsporsmal": prompter.hent(
            "spor.dokumentsporsmal", egne_regler="", ocr_merknad="",
            dokument="DOK", sporsmal="SPM"),
        "fyll_skjema.mal": prompter.hent(
            "fyll_skjema.mal", dokument="DOK", grunnlag="", mal="{}"),
        "korriger.forste_pass": prompter.hent(
            "korriger.forste_pass", usikre_blokk="", ocr_tekst="OCR"),
    }
    for navn, tekst in prompter_med_dokument.items():
        traff = False
        for hode, hale in api._PROMPT_ANKRE:
            i, j = tekst.find(hode), tekst.rfind(hale)
            if i != -1 and j > i:
                traff = True
                break
        assert traff, (
            f"«{navn}» treffer ingen av ankrene i _PROMPT_ANKRE "
            f"({api._PROMPT_ANKRE}) — lange dokumenter vil bli klippet "
            f"på feil sted uten at noen ser det.")


# ---------- 4) Lasteren: varm omlasting og ærlige feil ----------

def test_endring_virker_uten_omstart(tmp_path, monkeypatch):
    fil = tmp_path / "prompter.md"
    fil.write_text("[[proev]]\nførste\n[[/proev]]\n", encoding="utf-8")
    monkeypatch.setattr(prompter, "PROMPTER_STI", str(fil))
    monkeypatch.setattr(prompter, "_bufret",
                        {"mtime": None, "blokker": {}})
    assert prompter.hent("proev") == "første"

    fil.write_text("[[proev]]\nandre\n[[/proev]]\n", encoding="utf-8")
    os.utime(fil, (0, 0))          # tvinger fram en ny mtime
    assert prompter.hent("proev") == "andre", (
        "Endring i regelfila slo ikke gjennom uten omstart")


def test_manglende_blokk_navngir_seg_selv():
    with pytest.raises(KeyError) as feil:
        prompter.hent("spor.finnes_ikke")
    assert "spor.finnes_ikke" in str(feil.value)
    assert "spor.dokumentsporsmal" in str(feil.value)   # viser alternativene


def test_manglende_felt_sier_ifra_i_stedet_for_a_sende_halv_prompt():
    with pytest.raises(KeyError) as feil:
        prompter.hent("spor.dokumentsporsmal", egne_regler="",
                      ocr_merknad="", dokument="DOK")   # sporsmal mangler
    assert "sporsmal" in str(feil.value)


def test_manglende_regelfil_er_en_hoeylytt_feil(tmp_path, monkeypatch):
    """En server som svarer uten reglene sine, svarer feil i stillhet.
    Da er en krasj det ærlige."""
    monkeypatch.setattr(prompter, "PROMPTER_STI",
                        str(tmp_path / "borte.md"))
    monkeypatch.setattr(prompter, "_bufret", {"mtime": None, "blokker": {}})
    with pytest.raises(RuntimeError, match="Finner ikke regelfila"):
        prompter.hent("spor.dokumentsporsmal")


def test_promptversjonen_kommer_fra_regelfila():
    import dokument_api as api
    assert api._versjon_stempel()["prompt"] == prompter.versjon()
    assert prompter.versjon().strip()


def test_promptversjonen_foelger_fila_uten_omstart(tmp_path, monkeypatch):
    """R39: svaret skal kunne spores til NØYAKTIG den ordlyden som ga
    det. Ble versjonen frosset ved oppstart, ville en regelendring midt
    i drift gitt nye svar under gammelt versjonsstempel — sporet peker
    da på feil ordlyd, og det er verre enn ikke å spore i det hele tatt."""
    import dokument_api as api
    fil = tmp_path / "prompter.md"
    fil.write_text("[[versjon]]\np99\n[[/versjon]]\n", encoding="utf-8")
    monkeypatch.setattr(prompter, "PROMPTER_STI", str(fil))
    monkeypatch.setattr(prompter, "_bufret", {"mtime": None, "blokker": {}})
    assert api._versjon_stempel()["prompt"] == "p99"


def test_ulesbar_regelfil_midt_i_drift_beholder_forrige_utgave(capsys):
    """Lagrer noen fila i en editor akkurat idet et spørsmål kommer inn,
    skal ikke det spørsmålet feile. Vi beholder forrige gyldige utgave
    og sier ifra i loggen."""
    gyldig = prompter.hent("versjon")
    original = prompter.PROMPTER_STI
    try:
        prompter.PROMPTER_STI = original + ".finnes-ikke"
        assert prompter.hent("versjon") == gyldig
        assert "forrige gyldige utgave" in capsys.readouterr().out
    finally:
        prompter.PROMPTER_STI = original


# ---------- 5) Brukerens egne regelfiler ----------

def test_regelfilene_ligger_i_regler_mappa():
    for navn in ("egne_regler.txt", "egne_etiketter.txt"):
        sti = prompter.regelfil(navn)
        assert os.path.exists(sti), f"{navn} finnes ikke: {sti}"
        assert os.path.basename(os.path.dirname(sti)) == "regler", (
            f"{navn} ligger ikke i regler/ — da er reglene spredt igjen")


def test_bom_gjoer_ikke_en_kommentar_til_en_regel(tmp_path, monkeypatch):
    """Notepad lagrer med BOM. Uten «utf-8-sig» ble BOM-en hengende
    foran «#» på linje én, kommentarfilteret slapp den forbi, og en rad
    likhetstegn gikk inn i prompten som brukerens regel."""
    import dokument_api as api
    fil = tmp_path / "egne_regler.txt"
    fil.write_text("# =====================\n"
                   "Skriv beløp med valutakode.\n",
                   encoding="utf-8-sig")
    monkeypatch.setattr(api, "EGNE_REGLER_STI", str(fil))
    regler = api._egne_regler()
    assert "=====" not in regler, (
        "Kommentarlinja med BOM havnet i prompten som en regel")
    assert "Skriv beløp med valutakode." in regler


def test_egne_regler_er_norsk_og_lesbar():
    """CLAUDE.md §2: fila gikk en tur gjennom feil tegnsett og kom
    tilbake med arabiske bokstaver i «beløp» — rett inn i prompten."""
    raa = open(prompter.regelfil("egne_regler.txt"),
               encoding="utf-8-sig").read()
    fremmede = {t for t in raa if 0x0600 <= ord(t) <= 0x06FF}
    assert not fremmede, (
        f"Fremmede tegn i egne_regler.txt: {sorted(fremmede)} — fila er "
        f"trolig lagret med feil tegnsett (cp1256).")
