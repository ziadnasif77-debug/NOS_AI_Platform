"""
Evidence Selection målt mot baselinen §13.1 navngir (R208).

§13.1 sier at Evidence Selection «skal behandles som en målbar
produktkapabilitet», at «alle varianter sammenlignes mot en eksplisitt
baseline», og at baselinen er `first-N-context`. Den sier også hva som
skal måles: sju navngitte KPI-er.

Det var ikke gjort. Én av de sju — `answer_accuracy` — var målt
(109/133), og det var alt. De seks andre fantes ikke, og dermed heller
ikke svaret på om seleksjonen var verdt kontekstkostnaden sin.

Nå måles alle sju, og kampen er rettferdig: baselinen får NØYAKTIG samme
sidebudsjett. Da måler sammenligningen hvilke sider som velges — ikke
hvem som fikk sende mest tekst.

Målt (112 spørsmål med utledbar fasit, first-5-context som baseline):

    candidate_precision   17,1 % → 38,9 %
    candidate_recall      63,3 % → 90,6 %
    evidence_recall       53,6 % → 85,7 %
    context_tokens         1 100 →    839

Bedre på alle fire, og med MINDRE kontekst. `evidence_recall` er den
som betyr mest: baselinen lot modellen jobbe uten beviset i nesten
halvparten av spørsmålene.

Denne fila vokter fasitens tre tilstander og §13.1s forfremmelsesregel:
en variant promoteres bare når den er målbart bedre.
"""
import json
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

KORPUS = os.path.join("tester", "korpus", "sporsmaal_syntetisk_bunke.json")


@pytest.fixture(scope="module")
def korpus():
    with open(KORPUS, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------ #
#  Fasiten: tre tilstander, ikke to                                   #
# ------------------------------------------------------------------ #

def test_alle_sporsmaal_har_fasit_sider(korpus):
    """Uten dette feltet kan verken precision eller recall regnes."""
    mangler = [s["id"] for s in korpus["sporsmaal"]
               if "fasit_sider" not in s]
    assert not mangler, (
        f"{len(mangler)} spørsmål mangler «fasit_sider» — kjør "
        f"skript/utled_fasit_sider.py --skriv: {mangler[:5]}")


def test_negative_sporsmaal_har_tom_liste_ikke_null(korpus):
    """`[]` er en PÅSTAND: det finnes ingen side, og det er riktig
    svar. Ble de `null`, ville de blitt holdt utenfor målingen — og da
    forsvant nettopp de spørsmålene som prøver om systemet klarer å si
    «står ikke her»."""
    for sp in korpus["sporsmaal"]:
        if sp.get("type") == "negativ":
            assert sp["fasit_sider"] == [], (
                f"{sp['id']} er negativt, men har "
                f"fasit_sider={sp['fasit_sider']}")


def test_null_betyr_ikke_utledbart_og_holdes_utenfor(korpus):
    """`null` er noe annet enn `[]`. Uten skillet ville 21 spørsmål med
    utregnede summer («129 dager» står ingen steder ordrett) telt som
    negative, og seleksjonen fått straff for å velge sider den SKULLE
    valgt."""
    nuller = [s for s in korpus["sporsmaal"] if s["fasit_sider"] is None]
    assert nuller, "ingen null — da er skillet borte"
    for sp in nuller:
        assert sp.get("type") != "negativ", (
            f"{sp['id']} er negativt OG null — de to tilstandene er "
            "blandet, og da betyr ingen av dem noe")


def test_fasiten_dekker_nok_til_aa_maale(korpus):
    """En KPI regnet på en håndfull spørsmål er en anekdote."""
    med = [s for s in korpus["sporsmaal"] if s["fasit_sider"]]
    assert len(med) >= 90, (
        f"bare {len(med)} spørsmål har sider å måle mot")


def test_sidetallene_er_ekte_sidetall(korpus):
    for sp in korpus["sporsmaal"]:
        for n in (sp["fasit_sider"] or []):
            assert isinstance(n, int) and 1 <= n <= 10, (
                f"{sp['id']}: {n} er ikke et sidetall i en 10-siders bunke")


# ------------------------------------------------------------------ #
#  Baselinen er spesifikasjonens, ikke vår                            #
# ------------------------------------------------------------------ #

def test_baselinen_er_first_n_context():
    """§13.1 navngir den. Bytter noen den ut med noe mildere, blir
    enhver variant «bedre enn baselinen»."""
    import inspect
    import kjor_bevis_kpi as kpi
    kilde = inspect.getsource(kpi)
    assert "first-" in kilde and "first_n" in kilde


def test_baselinen_faar_samme_sidebudsjett():
    """Kampen skal handle om HVILKE sider som velges. Får baselinen
    færre sider, måler man sidebudsjett i stedet for seleksjon."""
    import inspect
    import kjor_bevis_kpi as kpi
    kilde = inspect.getsource(kpi.mal_sidevalg)
    assert "alle_sidetall[:maks_sider]" in kilde, (
        "baselinen bruker ikke samme sidebudsjett som bevisvalg")


def test_alle_sju_kpi_er_med():
    """§13.1 lister sju. Seks av dem fantes ikke før."""
    import inspect
    import kjor_bevis_kpi as kpi
    kilde = inspect.getsource(kpi)
    for navn in ("candidate_precision", "candidate_recall",
                 "evidence_recall", "answer_accuracy", "context_tokens",
                 "LLM_latency", "GPU_seconds_per_answer"):
        assert navn in kilde, f"KPI «{navn}» fra §13.1 mangler"


def test_uutledbare_holdes_utenfor_regnestykket():
    import inspect
    import kjor_bevis_kpi as kpi
    kilde = inspect.getsource(kpi.mal_sidevalg)
    assert "if fasit is None" in kilde and "utenfor" in kilde


# ------------------------------------------------------------------ #
#  Forfremmelsesregelen i §13.1                                       #
# ------------------------------------------------------------------ #

MAALING = os.path.join("data", "maalinger", "bevis_kpi.json")


@pytest.mark.skipif(not os.path.exists(MAALING),
                    reason="ingen måling ennå — kjør skript/kjor_bevis_kpi.py")
def test_seleksjonen_slaar_baselinen_paa_alle_kvalitets_kpi():
    """§13.1: «Kandidater promoteres bare når benchmark viser målbar
    forbedring på kvalitet eller ressursbruk uten uakseptabel
    regressjon». Bevisvalg er PÅ i produksjon — så den påstanden må
    holde, ellers skal den av."""
    with open(MAALING, encoding="utf-8") as f:
        m = json.load(f)
    for rad in m["sidevalg"]:
        if rad["kpi"] == "context_tokens":
            assert rad["bevisvalg"] <= rad["first_n"], (
                "bevisvalg sender MER kontekst enn baselinen og må da "
                "forsvare seg på kvalitet alene")
        else:
            assert rad["bevisvalg"] >= rad["first_n"], (
                f"{rad['kpi']}: bevisvalg {rad['bevisvalg']:.3f} er "
                f"DÅRLIGERE enn first-N {rad['first_n']:.3f} — da er den "
                "ikke lenger forsvarlig å ha på (§13.1)")


@pytest.mark.skipif(not os.path.exists(MAALING), reason="ingen måling ennå")
def test_evidence_recall_er_hoy_nok_til_aa_vaere_en_sikkerhetsmargin():
    """§13.1 kaller `evidence_recall` «sikkerhetsmargin før LLM». Er den
    lav, jobber modellen uten beviset — og da er et galt svar ikke
    modellens feil."""
    with open(MAALING, encoding="utf-8") as f:
        m = json.load(f)
    rad = [r for r in m["sidevalg"] if r["kpi"] == "evidence_recall"][0]
    assert rad["bevisvalg"] >= 0.80, (
        f"evidence_recall er {rad['bevisvalg']:.1%} — modellen mangler "
        "beviset i mer enn hvert femte spørsmål")
