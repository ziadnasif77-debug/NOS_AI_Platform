"""
OpenAPI-spekken må dekke ALLE ruter serveren faktisk svarer på.

Funnet ved å sammenligne Swagger-lista med rutene i koden: /ekko,
/innsyn og /innsyn/{id} manglet. For /ekko var det verst — det er
DIAGNOSE-endepunktet man trenger nettopp når et felt ikke kommer fram,
og det var usynlig i dokumentasjonen. Ingen fant det uten å lese koden.

Denne testen er en vakt: legger noen til en rute uten å dokumentere den,
feiler testen med rutenavnet.
"""
import re
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import dokument_api as api

# Ruter som med vilje står utenfor spekken: selve dokumentasjonen og
# spesifikasjonen. De beskriver API-et, de er ikke en del av det.
UTENFOR_SPEKKEN = {"/openapi", "/dokumentasjon"}


def _ruter_i_koden() -> set:
    """Stiene ruteren faktisk sammenligner mot, hentet fra kildekoden."""
    kilde = open(api.__file__, encoding="utf-8").read()
    return (set(re.findall(r'sti\s*==\s*["\'](/[\w/]+)', kilde))
            | set(re.findall(r'sti\.startswith\(\s*["\'](/[\w/]+)', kilde)))


def _normaliser(sti: str) -> str:
    """«/jobb/{id}/tekst» og «/jobb/» skal kunne sammenlignes med «/jobb»."""
    return re.sub(r"\{[^}]+\}", "", sti).replace("//", "/").rstrip("/")


def test_alle_ruter_er_dokumentert():
    spekk = {_normaliser(p) for p in api._openapi()["paths"]}
    mangler = sorted(
        r for r in _ruter_i_koden()
        if r not in UTENFOR_SPEKKEN and _normaliser(r) not in spekk)
    assert not mangler, (
        "Ruter som mangler i OpenAPI-spekken: %s. Legg dem inn i "
        "_openapi() — et udokumentert endepunkt finnes i praksis ikke."
        % ", ".join(mangler))


def test_diagnoseendepunktet_er_dokumentert():
    """/ekko fortjener sin egen vakt: det er det eneste verktøyet som
    viser hva serveren FAKTISK mottok, og verdien er null hvis ingen vet
    at det finnes."""
    ekko = api._openapi()["paths"].get("/ekko")
    assert ekko, "/ekko mangler i OpenAPI-spekken"
    tekst = (ekko["post"]["summary"] + ekko["post"].get("description", ""))
    assert "parser_ser" in str(ekko) or "parser_ser" in tekst
    assert "raa_deler" in str(ekko)


def test_svarmodellene_er_dokumentert():
    """Uten components.schemas viser ikke Swagger noen «Schemas»-seksjon, og
    en integrator må kalle API-et for å finne ut hva feltene heter."""
    skjemaer = api._openapi()["components"]["schemas"]
    # De modellene en klient faktisk leser mot
    for navn in ("DokumentSvar", "FelterDel", "StrukturDel", "SvarDel",
                 "SkjemaDel", "Dokumentdato", "EkkoSvar", "Feilsvar"):
        assert navn in skjemaer, f"Mangler svarmodell: {navn}"


def test_ingen_brutte_referanser():
    """En $ref som peker på et skjema som ikke finnes gjør at Swagger viser
    feil i stedet for modellen."""
    import json
    spekk = api._openapi()
    definerte = set(spekk["components"]["schemas"])
    brukte = set(re.findall(r"#/components/schemas/(\w+)",
                            json.dumps(spekk, ensure_ascii=False)))
    assert not (brukte - definerte), \
        f"Brutte $ref: {sorted(brukte - definerte)}"


def test_belop_er_dokumentert_i_begge_former():
    """Den formen som overrasker mest: «belop» er et TALL i felter-delen,
    men en LISTE av objekter med kontekst i struktur-delen. Står det ikke
    i modellen, oppdager klienten det først i produksjon."""
    skjemaer = api._openapi()["components"]["schemas"]
    felt = skjemaer["DeterministiskeFelter"]["properties"]["belop"]
    assert felt["type"] == "number"
    struktur = skjemaer["StrukturDel"]["properties"]["belop"]
    assert struktur["type"] == "array"
    assert struktur["items"]["$ref"].endswith("/Belop")


def test_schemas_seksjonen_er_synlig_i_swagger():
    """defaultModelsExpandDepth: -1 skjuler «Schemas» helt. Da hjelper det
    ikke at modellene finnes i spekken."""
    assert "defaultModelsExpandDepth: -1" not in api._SWAGGER_HTML
    assert "defaultModelsExpandDepth: 0" in api._SWAGGER_HTML


def test_veiledningen_ligger_under_endepunktlista():
    html = api._SWAGGER_HTML
    assert html.index('<div class="veiledning">') > html.index('id="swagger-ui"')
    assert html.count("<section>") == html.count("</section>")


def test_spekken_er_gyldig_json_struktur():
    """Hver dokumentert sti må ha minst én HTTP-metode med responses."""
    for sti, metoder in api._openapi()["paths"].items():
        assert metoder, f"{sti} har ingen metoder"
        for navn, def_ in metoder.items():
            assert navn in ("get", "post", "put", "delete", "patch"), \
                f"{sti}: ukjent metode {navn}"
            assert def_.get("summary"), f"{sti}.{navn} mangler summary"
            assert def_.get("responses"), f"{sti}.{navn} mangler responses"
