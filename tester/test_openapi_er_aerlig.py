"""OpenAPI-spekken skal love det API-et faktisk gjør.

Målt på spekken slik en klientgenerator leser den:

  · `securitySchemes: ApiKeyAuth` var DEKLARERT, men aldri PÅFØRT —
    ingen `security` på rotnivå, og ingen på noen av de 13
    operasjonene. En generert klient sendte derfor ingen nøkkel og fikk
    401 på første kall. Ordningen sto der og gjorde ingenting.
  · 27 av 27 objektskjemaer manglet `required`, så en generator gjorde
    HVERT felt valgfritt. Det er stikk motsatt av R118, som er selve
    løftet vårt: nøklene er ALLTID til stede. Spekken underdrev vår
    egen garanti, og tvang klienten til null-sjekker vi har lovet at
    den slipper.
  · 13 av 13 operasjoner manglet `operationId`, så generatoren fant på
    metodenavn ut fra stien — navn som skifter neste gang en sti gjør
    det.
  · 9 svar hadde ingen skjemabeskrivelse, deriblant jobbendepunktene
    som R131 brukte et helt punkt på å gjøre formstabile. Den
    kontrakten var usynlig for den som genererte en klient.

Den viktigste testen her er `test_required_stemmer_med_ekte_svar`:
`required` er en PÅSTAND, og en påstand som ikke er målt er verre enn
ingen — den får klienten til å droppe null-sjekker den faktisk trengte.
"""
import os
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "skript"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api
from syntetiske_nummer import lag_fnr


@pytest.fixture(scope="module")
def spec():
    return api._openapi()


# ------------------------------------------------------------------ #
#  1. Sikkerhetsordningen er PÅFØRT, ikke bare deklarert               #
# ------------------------------------------------------------------ #

def test_sikkerhetsordningen_er_paafort(spec):
    assert spec.get("security") == [{"ApiKeyAuth": []}], (
        "securitySchemes var deklarert uten å være påført — en generert "
        "klient sendte da ingen nøkkel og fikk 401 på første kall")
    assert "ApiKeyAuth" in spec["components"]["securitySchemes"]


def test_de_apne_rutene_sier_UTTRYKKELIG_at_de_er_apne(spec):
    """`security: []` er den eksplisitte måten. Å bare utelate feltet
    ville arvet rotnivåets krav — og da ville spekken sagt at
    helsesjekken krever nøkkel, som den ikke gjør."""
    assert spec["paths"]["/hjelp"]["get"]["security"] == []


def test_datarutene_arver_kravet(spec):
    for sti in ("/dokument", "/jobb", "/spor", "/sladd"):
        op = spec["paths"][sti]["post"]
        assert op.get("security") != [], (
            f"{sti} er merket åpen — den bærer dokumentdata")


# ------------------------------------------------------------------ #
#  2. required er MÅLT, ikke påstått                                   #
# ------------------------------------------------------------------ #

DOK = ("[Side 1 av 1]\nNAV Arbeid og ytelser\nVedtak om sykepenger\n"
       "Dokumentdato: 04.03.2026\nOpplysninger om: Ola Nordmann\n"
       f"Fodselsnummer: {lag_fnr(0)}\nSaksnummer: 12345678\n")

# Skjema → hvor i et ekte svar objektet ligger. Bare det som lar seg
# peke på entydig; resten dekkes av formstabilitetstestene.
MAALEPUNKT = {
    "Part": ("dokumentprofil", "part"),
    "Dekning": ("dokumentprofil", "dekning"),
    "Sammendrag": ("dokumentprofil", "sammendrag"),
}


def _svar():
    ktx = api.DokumentKontekst(DOK, antall_sider=1, filnavn="a.txt")
    return {"dokumentprofil": api._profilform(ktx.profil, "full")}


def test_required_stemmer_med_ekte_svar(spec):
    """Selve poenget. `required` sier «denne nøkkelen er alltid der».
    Er den ikke det, har vi byttet ut én løgn med en verre: en klient
    som dropper null-sjekken sin fordi vi lovet den bort."""
    svar = _svar()
    skjema = spec["components"]["schemas"]
    mangler = []
    for navn, sti in MAALEPUNKT.items():
        if navn not in skjema:
            continue
        node = svar
        for bit in sti:
            node = (node or {}).get(bit)
        if not isinstance(node, dict):
            continue
        for felt in skjema[navn].get("required", []):
            if felt not in node:
                mangler.append(f"{navn}.{felt}")
    assert not mangler, (
        "required lover felter som IKKE er i svaret: " + ", ".join(mangler))


def test_alle_objektskjemaer_erklaerer_required(spec):
    uten = [n for n, s in spec["components"]["schemas"].items()
            if s.get("type") == "object" and s.get("properties")
            and not s.get("required")]
    assert not uten, f"objektskjemaer uten required: {uten}"


def test_nullable_er_noe_ANNET_enn_utelatt(spec):
    """Skillet spekken ikke fikk fram: `nullable` sier at VERDIEN kan
    være null (R128 — «vi så ikke etter»), ikke at nøkkelen kan mangle
    (R118 — det skjer aldri). Et felt kan altså være både påkrevd og
    nullable, og de fleste av våre er nettopp det."""
    part = spec["components"]["schemas"]["Part"]
    assert "fnr" in part["required"]
    assert part["properties"]["fnr"].get("nullable") is True


# ------------------------------------------------------------------ #
#  3. Navn og referanser                                               #
# ------------------------------------------------------------------ #

def test_hver_operasjon_har_et_stabilt_navn(spec):
    uten = [f"{m.upper()} {p}" for p, d in spec["paths"].items()
            for m, o in d.items()
            if isinstance(o, dict) and not o.get("operationId")]
    assert not uten, f"operasjoner uten operationId: {uten}"


def test_navnene_er_entydige(spec):
    navn = [o["operationId"] for d in spec["paths"].values()
            for o in d.values() if isinstance(o, dict)]
    assert len(navn) == len(set(navn)), "to operasjoner deler operationId"


def test_navnet_utledes_av_metode_og_sti():
    assert api._operasjonsnavn("post", "/jobb/{id}/avbryt") == \
        "postJobbIdAvbryt"
    assert api._operasjonsnavn("get", "/hjelp") == "getHjelp"


# Brutte `$ref` voktes av `test_kontraktsvakt.py:
# test_ingen_brutte_referanser_i_openapi`. Den lå der først, og to
# vakter for samme sak er den dupliseringen resten av denne økta har
# handlet om å fjerne (R126). Den ble utvidet til å FØLGE pekeren i
# stedet for å sammenligne siste ledd mot skjemanavnene — den gamle
# formen meldte en gyldig `#/components/responses/Feil` som brutt.


# ------------------------------------------------------------------ #
#  4. Jobbkontrakten (R131) står i spekken                             #
# ------------------------------------------------------------------ #

def test_jobbsvaret_har_en_form_i_spekken(spec):
    """R131 gjorde jobbsvaret formstabilt nettopp for pollende roboter.
    Den kontrakten var usynlig for den som genererte en klient."""
    jobb = spec["components"]["schemas"]["Jobb"]
    for felt in ("status", "versjon", "avbrutt", "feil", "sider_ferdig",
                 "sider_totalt", "dokumentdato", "tekst_tilgjengelig"):
        assert felt in jobb["properties"], felt
    assert "avbrutt" in jobb["required"]
    assert "feil" in jobb["required"]


def test_jobbstien_peker_paa_jobbskjemaet(spec):
    svar = spec["paths"]["/jobb/{id}"]["get"]["responses"]["200"]
    ref = svar["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/Jobb")


def test_de_ubeskrevne_svarene_er_faerre_enn_foer(spec):
    """Ærlig grense: fem svar har fortsatt ingen skjemabeskrivelse
    (/hjelp, /spor, de to /innsyn og 409-teksten). De er ikke glemt —
    de er ikke gjort ennå, og tallet står her så det ikke vokser i
    stillhet."""
    tomme = [f"{m.upper()} {p} {kode}"
             for p, d in spec["paths"].items()
             for m, o in d.items() if isinstance(o, dict)
             for kode, sv in (o.get("responses") or {}).items()
             if not (sv.get("content") or sv.get("$ref"))]
    assert len(tomme) <= 4, f"flere svar uten form enn før: {tomme}"
