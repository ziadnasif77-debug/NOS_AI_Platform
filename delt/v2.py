"""v2-formen av svaret fra dokumentendepunktene.

Revisjonen fant at v1 har 21 toppnøkler uten noen ordning: fakta om
dokumentet, opplysninger om forespørselen og diagnostikk ligger om
hverandre. Tre grupper svarer på tre ulike spørsmål:

    data          hva står i dokumentet
    metadata      hva ble sendt inn, og hva svarte
    diagnostikk   hvordan gikk det

I v2 er de også skilt i JSON-en. Utgåtte navn er borte HER — men bare
her: v1 leverer dem uendret, og ingen klient brekker av at v2 finnes.

RETNINGEN ER MOTSATT AV PLANEN, MED VILJE
    Punkt 34 sa «v1 produseres som projeksjon av v2». Vi gjør det
    omvendt: v2 er en projeksjon av det v1 alt bygger. Grunnen er at v1
    er i drift hos skjøre UiPath-klienter og er gjerdet inn av over 800
    tester. Å legge om PRODUKSJONSVEIEN til v1 for å gå gjennom en ny
    modell er en reell risiko for at et felt blir en tanke annerledes —
    og gevinsten ville vært null utenfra. Sluttilstanden er den samme;
    dette er den billige veien dit.

    Prisen er at v1 og v2 kan gli fra hverandre hvis noen legger et felt
    bare ett sted. Derfor er kartet under UTTØMMENDE: hver v1-nøkkel er
    enten plassert eller uttrykkelig droppet, og en vakttest feiler på
    en nøkkel som ikke står i noen av listene.
"""

# Hvor hver v1-toppnøkkel havner. Uttømmende med vilje — se docstringen.
_METADATA = ("filnavn", "antall_sider", "antall_tegn", "versjon")
_DIAGNOSTIKK = ("status", "valg", "varsler", "kvalitet", "opphav",
                "modell_brukt", "fra_cache", "tid_sekunder", "kilde")
_DATA = ("dokumentprofil", "tekst", "felter", "struktur", "svar", "skjema",
         "korriger", "korrigert_tekst", "koordinater", "strekkoder",
         "handskrift", "resultater")
# «ok» og «status» er svarets toppsvar og blir liggende på rot (R83): de
# svarer på ulike spørsmål, og begge skal kunne leses uten å gå ned et
# nivå. «status» står derfor BEGGE steder, som i v1.
_ROT = ("ok", "status")

# Navn som er merket utgått i v1 (R99). De finnes ikke i v2 — det er
# hele poenget med et nytt hovedversjonsnummer. Stien er relativ til
# dokumentprofilen.
UTGAATT_I_PROFIL = (
    ("eier",),                       # bruk «part»
    ("andre_personer",),             # bruk «andre_fodselsnummer»
    ("sammendrag", "sikkerhet"),     # bruk «konfidens»
    ("part", "sikkerhet"),           # bruk «grunnlag»
    ("ytelse", "implementasjon"),    # bruk «dekning.ytelse»
)


def _uten(node, sti):
    """Fjerner én sti fra et nøstet kart, uten å endre originalen."""
    if not sti or not isinstance(node, dict) or sti[0] not in node:
        return node
    ny = dict(node)
    if len(sti) == 1:
        ny.pop(sti[0])
    else:
        ny[sti[0]] = _uten(ny[sti[0]], sti[1:])
    return ny


def rydd_profil(profil):
    """Profilen uten de utgåtte navnene, og med `ar` omdøpt.

    `dokument.ar` sto rett ved siden av `dokument.alder.aar` — to
    skrivemåter av samme bokstav, to betydninger (årstallet kontra antall
    år gammelt). I v2 heter den `aarstall`, som ikke kan forveksles."""
    if not isinstance(profil, dict):
        return profil
    ryddet = profil
    for sti in UTGAATT_I_PROFIL:
        ryddet = _uten(ryddet, sti)
    dokument = ryddet.get("dokument")
    if isinstance(dokument, dict) and "ar" in dokument:
        ryddet = dict(ryddet)
        nytt = {("aarstall" if k == "ar" else k): v
                for k, v in dokument.items()}
        ryddet["dokument"] = nytt
    return ryddet


def til_v2(svar: dict) -> dict:
    """v1-svaret projisert til v2-form.

    Ukjente nøkler havner i `data`: et nytt felt er som regel et faktum
    om dokumentet, og å droppe det ville vært verre enn å plassere det
    litt feil. Vakttesten fanger opp at det skjer, så plasseringen kan
    avgjøres bevisst."""
    if not isinstance(svar, dict):
        return svar

    data, metadata, diagnostikk, rot = {}, {}, {}, {}
    for nokkel, verdi in svar.items():
        if nokkel in _ROT:
            rot[nokkel] = verdi
            if nokkel == "status":
                diagnostikk[nokkel] = verdi
        elif nokkel in _METADATA:
            metadata[nokkel] = verdi
        elif nokkel in _DIAGNOSTIKK:
            diagnostikk[nokkel] = verdi
        else:
            data[nokkel] = verdi

    # Profilen flates UT i data: i v1 måtte man ned i «dokumentprofil»
    # for å finne parten, og «dokumentprofil.dokument.dato» er tre ledd
    # for dokumentets dato. Seksjonene ER dataene.
    profil = rydd_profil(data.pop("dokumentprofil", None))
    if isinstance(profil, dict):
        metadata["skjemaversjon"] = profil.get("skjemaversjon")
        # «fil» handler om FILEN vi fikk, ikke om innholdet
        if isinstance(profil.get("fil"), dict):
            metadata["fil"] = profil["fil"]
        # «dekning» sier hva SYSTEMET kan ennå — diagnostikk, ikke et
        # faktum om dokumentet
        if "dekning" in profil:
            diagnostikk["dekning"] = profil["dekning"]
        for nokkel, verdi in profil.items():
            if nokkel not in ("skjemaversjon", "fil", "dekning"):
                data[nokkel] = verdi
    elif profil is not None:
        data["dokumentprofil"] = profil        # feilobjekt — la det stå

    return {**rot, "data": data, "metadata": metadata,
            "diagnostikk": diagnostikk}
