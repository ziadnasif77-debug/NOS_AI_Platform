"""
Målinger og `GET /metrics` (R191), og vakten over ADR-registeret.

De to farene ved et metrics-endepunkt er kardinalitet (én tidsserie per
jobb-id fyller minnet med søppel ingen kan spørre på) og PII (et
`/metrics` som kan inneholde innhold, må personvernvurderes før noen
får skrape det). Begge voktes her.
"""
import io
import os
import re
import sys

sys.path.insert(0, ".")

import pytest

from delt import maalinger


@pytest.fixture(autouse=True)
def rent_bord():
    maalinger.nullstill()
    yield
    maalinger.nullstill()


# ------------------------------------------------------------------ #
#  Kardinalitet: antall serier styres av KODEN, ikke av trafikken     #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("sti,forventet", [
    ("/dokument", "/dokument"),
    ("/dokument/operasjoner", "/dokument/operasjoner"),
    ("/dokument?struktur=ja", "/dokument"),
    ("/jobb/9f3c-4a1e-bb20", "/jobb"),
    ("/innsyn/abc123", "/innsyn"),
    ("/api/v1/spor", "/spor"),
    ("/api/v1/jobb/xyz", "/jobb"),
    ("/noe-ukjent", "annet"),
    ("", "annet"),
])
def test_stier_normaliseres_til_ruter(sti, forventet):
    assert maalinger.rute(sti) == forventet


def test_operasjoner_spises_ikke_av_dokument():
    """Rekkefølgen i _RUTER betyr noe: «/dokument» ville ellers slukt
    «/dokument/operasjoner», og de to kan ikke skilles i grafene."""
    assert maalinger.rute("/dokument/operasjoner") == "/dokument/operasjoner"


def test_tusen_ulike_jobb_ider_gir_EN_tidsserie():
    """Den konkrete katastrofen: uten normalisering vokser minnet med
    trafikken, og etter en uke er /metrics ubrukelig."""
    for i in range(1000):
        maalinger.tell("nav_foresporsler_total",
                       sti=maalinger.rute(f"/jobb/{i}-{i}-{i}"), kode="200")
    linjer = [l for l in maalinger.tekst().splitlines()
              if l.startswith("nav_foresporsler_total{")]
    assert len(linjer) == 1
    assert linjer[0].endswith(" 1000")


# ------------------------------------------------------------------ #
#  Formatet Prometheus faktisk leser                                  #
# ------------------------------------------------------------------ #

def test_metrikknavn_er_lovlige_uten_aeoeaa():
    """Prometheus tillater bare [a-zA-Z_:][a-zA-Z0-9_:]* — æøå ville
    gjort navnene ulovlige, og hele svaret uleselig for skraperen."""
    maalinger.tell("nav_foresporsler_total", sti="/dokument", kode="200")
    maalinger.observer("nav_foresporsel_sekunder", 1.0, sti="/dokument")
    maalinger.sett("nav_kapasitet", 4)
    lovlig = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
    for linje in maalinger.tekst().splitlines():
        if not linje or linje.startswith("#"):
            continue
        navn = linje.split("{")[0].split(" ")[0]
        assert lovlig.match(navn), f"ulovlig metrikknavn: {navn}"


def test_histogram_botter_er_kumulative():
    """Prometheus krever at hver bøtte teller ALT som er mindre enn
    grensen. Er de ikke kumulative, blir P95 feil uten å se feil ut."""
    for sekunder in (0.02, 0.3, 3.0, 45.0):
        maalinger.observer("nav_foresporsel_sekunder", sekunder, sti="/dokument")
    tall = {}
    for linje in maalinger.tekst().splitlines():
        m = re.match(r'nav_foresporsel_sekunder_bucket\{.*le="([^"]+)"\} (\d+)',
                     linje)
        if m:
            tall[m.group(1)] = int(m.group(2))
    assert tall["0.05"] == 1
    assert tall["0.5"] == 2
    assert tall["5"] == 3
    assert tall["+Inf"] == 4
    grenser = [g for g in tall if g != "+Inf"]
    sortert = sorted(grenser, key=float)
    verdier = [tall[g] for g in sortert]
    assert verdier == sorted(verdier), "bøttene er ikke kumulative"


def test_sum_og_count_foelger_observasjonene():
    for s in (1.0, 2.0, 3.0):
        maalinger.observer("nav_foresporsel_sekunder", s, sti="/spor")
    tekst = maalinger.tekst()
    assert 'nav_foresporsel_sekunder_sum{sti="/spor"} 6' in tekst
    assert 'nav_foresporsel_sekunder_count{sti="/spor"} 3' in tekst


def test_hver_metrikk_har_help_og_type():
    """Uten HELP og TYPE er en metrikk et tall ingen vet hva betyr."""
    maalinger.tell("nav_ocr_sider_total", 5)
    maalinger.sett("nav_borealis_klar", 1)
    tekst = maalinger.tekst()
    for navn in ("nav_ocr_sider_total", "nav_borealis_klar"):
        assert f"# HELP {navn} " in tekst
        assert f"# TYPE {navn} " in tekst


def test_hvert_beskrevet_navn_har_norsk_forklaring():
    for navn, (hjelp, type_) in maalinger._BESKRIVELSER.items():
        assert hjelp and hjelp != navn, f"{navn} mangler forklaring"
        assert type_ in ("counter", "gauge", "histogram")


# ------------------------------------------------------------------ #
#  PII: det skal ikke finnes en vei for innhold inn hit               #
# ------------------------------------------------------------------ #

def test_etikettverdier_kan_ikke_brekke_formatet():
    """En etikett med anførselstegn eller linjeskift ville laget en
    ugyldig linje — og i verste fall smuglet inn en falsk metrikk.

    Teksten kan gjerne stå igjen INNE i etikettverdien; det er trygt så
    lenge den ikke blir en egen linje. Det er nettopp det som testes:
    én linje ut, og hver linje velformet."""
    maalinger.tell("nav_gjennomgang_total",
                   grunn='sprø"\nnav_falsk_metrikk 999\n#')
    tekst = maalinger.tekst()
    verdilinjer = [l for l in tekst.splitlines()
                   if l and not l.startswith("#")
                   and not l.startswith("nav_oppetid_sekunder")]
    assert len(verdilinjer) == 1, (
        "etikettverdien ble til flere linjer — da kan hva som helst "
        f"smugles inn: {verdilinjer}")
    assert not any(l.startswith("nav_falsk_metrikk") for l in verdilinjer)
    for linje in verdilinjer:
        assert re.match(
            r"^[a-zA-Z_:][a-zA-Z0-9_:]*(\{[^}]*\})? -?[\d.e+]+$", linje), linje


def test_etikettverdier_er_avkortet():
    maalinger.tell("nav_gjennomgang_total", grunn="x" * 500)
    for linje in maalinger.tekst().splitlines():
        assert len(linje) < 200


# ------------------------------------------------------------------ #
#  Serverens hook: metrikker overlever at tilgangsloggen slås av      #
# ------------------------------------------------------------------ #

def test_metrikker_telles_selv_uten_tilgangslogg(monkeypatch):
    """Den som slår av tilgangsloggen av personvernhensyn, skal ikke
    miste kapasitetstallene på kjøpet."""
    sys.path.insert(0, "skript")
    import dokument_api as api
    monkeypatch.setattr(api, "TILGANGSLOGG_STI", "")

    class Falsk:
        path = "/dokument"
        command = "POST"
        _t0_req = 0.0
        _tallvakt = {"stoppet": 2, "forsok": 1}
        _gjennomgang_grunn = "lav_ocr_konfidens"

        def _klient_ip(self):
            return "127.0.0.1"

    api._skriv_tilgang(Falsk(), 200)
    tekst = maalinger.tekst()
    assert 'nav_foresporsler_total{kode="200",sti="/dokument"} 1' in tekst
    assert 'nav_tallvakt_total{utfall="stoppet"} 1' in tekst
    assert 'nav_gjennomgang_total{grunn="lav_ocr_konfidens"} 1' in tekst


def test_mellombaandets_grunn_klippes_saa_typen_ikke_sprenger_kardinaliteten(
        monkeypatch):
    sys.path.insert(0, "skript")
    import dokument_api as api
    monkeypatch.setattr(api, "TILGANGSLOGG_STI", "")

    class Falsk:
        path = "/dokument"
        command = "POST"
        _t0_req = 0.0
        _gjennomgang_grunn = "mellomband_holdt_tilbake:faktura"

        def _klient_ip(self):
            return "127.0.0.1"

    api._skriv_tilgang(Falsk(), 200)
    assert ('nav_gjennomgang_total{grunn="mellomband_holdt_tilbake"} 1'
            in maalinger.tekst())


# ------------------------------------------------------------------ #
#  ADR-registeret skal være ekte, ikke en tom mappe                   #
# ------------------------------------------------------------------ #

ADR_MAPPE = os.path.join("docs", "beslutninger")

PAAKREVDE_FELT = ("## Decision", "## Reason", "## Alternatives Considered",
                  "## Trade-offs", "## Decision Value",
                  "## Debt Introduced", "## Risk", "## Owner",
                  "## Review Trigger", "## Review Date",
                  "## Exit Strategy")


def _adr_filer():
    return sorted(f for f in os.listdir(ADR_MAPPE)
                  if f.startswith("ADR-") and f.endswith(".md"))


def test_registeret_har_beslutninger():
    assert len(_adr_filer()) >= 5, (
        "et tomt ADR-register er verre enn ingen: det ser ut som om "
        "beslutningene er dokumentert")


@pytest.mark.parametrize("fil", _adr_filer())
def test_hver_adr_fyller_hele_malen(fil):
    """§29: alle felter fylles ut. Står et felt tomt, er beslutningen
    ikke tatt ennå."""
    tekst = io.open(os.path.join(ADR_MAPPE, fil), encoding="utf-8").read()
    for felt in PAAKREVDE_FELT:
        assert felt in tekst, f"{fil} mangler «{felt}»"
    # Ingen seksjon får stå tom. «Review Date» er unntatt lengdekravet:
    # en dato ER komplett på ti tegn — den skal derimot være en ekte
    # dato, ikke «snart».
    for felt in PAAKREVDE_FELT:
        etter = tekst.split(felt, 1)[1]
        innhold = etter.split("\n##", 1)[0]
        innhold = "\n".join(l for l in innhold.splitlines()
                            if not l.startswith("#")).strip()
        if felt == "## Review Date":
            assert re.match(r"^\d{4}-\d{2}-\d{2}$", innhold), (
                f"{fil}: «Review Date» må være en dato (ÅÅÅÅ-MM-DD), "
                f"ikke «{innhold[:40]}»")
            continue
        assert len(innhold) > 20, f"{fil}: «{felt}» er tom eller for tynn"


@pytest.mark.parametrize("fil", _adr_filer())
def test_review_trigger_er_maalbar_ikke_naar_vi_faar_tid(fil):
    """§29: «Vi gjør det senere» er ikke en begrunnelse, og en
    midlertidig løsning uten målbar trigger er ikke tillatt."""
    tekst = io.open(os.path.join(ADR_MAPPE, fil), encoding="utf-8").read()
    trigger = tekst.split("## Review Trigger", 1)[1].split("\n##", 1)[0].lower()
    for forbudt in ("når vi får tid", "senere", "ved anledning"):
        assert forbudt not in trigger, (
            f"{fil}: review-triggeren er ikke målbar («{forbudt}»)")


@pytest.mark.parametrize("fil", _adr_filer())
def test_hver_adr_staar_i_registeret(fil):
    """En ADR ingen finner, er ikke dokumentasjon."""
    indeks = io.open(os.path.join(ADR_MAPPE, "LES_MEG.md"),
                     encoding="utf-8").read()
    nummer = fil.split("-")[1]
    assert nummer in indeks, f"{fil} mangler i registertabellen i LES_MEG.md"
