"""
R6-porten og det den fant (§26/§30, R206).

§26 og §30 krever det samme, med samme ordlyd begge steder: «Samme
dokument kjørt 10 ganger under identisk engine/model/configuration skal
gi byte-for-byte identisk resultat-JSON». Det var aldri prøvd — det
nærmeste var to kjøringer av 500-sidersmålingen.

Porten (`skript/kjor_determinismeport.py`) fant et ekte brudd med en
gang, og det satt et sted ingen hadde sett etter: `Llama` er ETT objekt
som lever hele serverens levetid, og llama.cpp beholder KV-cachen mellom
kall. Deler en ny prompt forstavelse med den forrige, gjenbrukes de
cachede tokenene — og gjenbruksveien gir litt andre flyttallssummer enn
en fersk evaluering. Ved temperature=0 er det nok til å vippe ett token.

Målt, SAMME dokument og SAMME spørsmål, tre ganger:

    etter et skannet dokument   319 tegn
    etter samme spørsmål        424 tegn
    etter et annet spørsmål     398 tegn

Svaret avhang altså av hva serveren gjorde FØR det. To saksbehandlere
med samme dokument fikk ulikt svar, og ingen av dem kunne se hvorfor.

Denne fila vokter tre ting: at nullstillingen finnes og ligger innenfor
låsen, at lista over flyktige felter ikke vokser i stillhet, og at
porten faktisk sjekker sine egne forutsetninger.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest


# ------------------------------------------------------------------ #
#  R206: nullstillingen                                              #
# ------------------------------------------------------------------ #

def test_konteksten_nullstilles_for_hvert_modellkall():
    """Uten `reset()` avhenger svaret av forrige forespørsel."""
    import inspect
    import dokument_api as api
    kilde = inspect.getsource(api._borealis_generer_intern)
    assert "llm.reset()" in kilde, (
        "konteksten nullstilles ikke før generering — da gjenbruker "
        "llama.cpp KV-cachen fra forrige kall, og samme dokument gir "
        "ulikt svar avhengig av hva som ble spurt om før (R206)")


def test_nullstillingen_ligger_innenfor_laasen():
    """Utenfor låsen kunne et annet kall rukket å fylle cachen igjen
    mellom `reset()` og genereringen — og da er vi like langt."""
    import inspect
    import dokument_api as api
    kilde = inspect.getsource(api._borealis_generer_intern)
    las = kilde.index("with _borealis_las")
    reset = kilde.index("llm.reset()")
    generering = kilde.index("create_chat_completion")
    assert las < reset < generering, (
        "reset() ligger ikke mellom låsen og genereringen — "
        "rekkefølgen er hele poenget (R206)")


def test_temperaturen_er_null():
    """Grådig dekoding er en forutsetning for at nullstillingen skal
    holde. Skrus temperaturen opp, er determinismen borte uansett."""
    import inspect
    import dokument_api as api
    kilde = inspect.getsource(api._borealis_generer_intern)
    assert "temperature=0.0" in kilde


# ------------------------------------------------------------------ #
#  Porten skal ikke kunne uthules                                    #
# ------------------------------------------------------------------ #

def test_flyktige_felter_er_faa_og_begrunnet():
    """Lista er en ERKLÆRING, ikke et sluk. Slik slutter en port å bety
    noe: ett felt om gangen, hvert med sin lille grunn."""
    import kjor_determinismeport as port
    assert len(port.FLYKTIGE) <= 3, (
        f"lista over flyktige felter har vokst til {len(port.FLYKTIGE)}: "
        f"{sorted(port.FLYKTIGE)}. Hvert nytt felt gjør porten svakere — "
        "er det virkelig umulig å gjøre det stabilt?")
    for felt, grunn in port.FLYKTIGE.items():
        assert grunn and len(grunn) > 15, (
            f"«{felt}» står i lista uten en brukbar grunn")


def test_maalt_kjoretid_er_det_eneste_som_maa_variere():
    """Den ene som ikke KAN være lik. Alt annet skal kunne være det."""
    import kjor_determinismeport as port
    assert "tid_sekunder" in port.FLYKTIGE


def test_porten_proever_bade_ocr_veien_og_modellveien():
    """Determinisme på én vei er ikke determinisme. Tekstlaget hopper
    over OCR helt; den skannede går gjennom hele OCR-veien; og
    fritekstsvaret er det eneste som prøver GENERERING — som var
    nettopp det som viste seg å være ustabilt."""
    import kjor_determinismeport as port
    navn = [n for n, _, _ in port.DOKUMENTER]
    assert any("tekstlag" in n for n in navn)
    assert any("skannet" in n for n in navn)
    assert any("fritekst" in n for n in navn), (
        "porten prøver ingen fri tekstgenerering — og det var den veien "
        "som faktisk var ødelagt (R206)")


def test_porten_krever_at_cachen_er_av():
    """Svarer cachen, beviser porten at CACHEN er stabil — ikke at
    lesingen er deterministisk. Det er det siste §26 spør om."""
    import inspect
    import kjor_determinismeport as port
    kilde = inspect.getsource(port.kjor_ett)
    assert "fra_cache" in kilde and "ugyldig" in kilde, (
        "porten sjekker ikke om svarene kom fra cachen")


def test_sammenligningen_er_uavhengig_av_noekkelrekkefolge():
    """Rekkefølgen på nøkler i en ordbok er et artefakt av hvordan
    svaret ble bygget, ikke en del av svaret."""
    import kjor_determinismeport as port
    a = {"b": 1, "a": {"y": 2, "x": 3}}
    b = {"a": {"x": 3, "y": 2}, "b": 1}
    assert port.kanonisk(a) == port.kanonisk(b)


def test_flyktige_felter_fjernes_paa_alle_nivaaer():
    """`tid_sekunder` finnes både i roten og inne i `svar`."""
    import kjor_determinismeport as port
    ut = port.uten_flyktige(
        {"tid_sekunder": 1, "svar": {"tid_sekunder": 2, "tekst": "a"},
         "liste": [{"tid_sekunder": 3, "n": 1}]})
    assert ut == {"svar": {"tekst": "a"}, "liste": [{"n": 1}]}


def test_avvik_rapporteres_som_stier_ikke_som_en_diff():
    """Et svar er på 300 000 tegn. En diff er ubrukelig; en sti som
    «.svar.svar» sier hvor man skal se."""
    import kjor_determinismeport as port
    stier = port._stier_som_avviker({"a": {"b": 1}}, {"a": {"b": 2}})
    assert stier and stier[0][0] == ".a.b"
