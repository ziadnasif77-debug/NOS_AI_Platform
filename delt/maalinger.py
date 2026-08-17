"""Målinger: tellere og histogrammer for `GET /metrics`.

Tilgangsloggen svarer på «hva skjedde i denne forespørselen». Den svarer
ikke på «hvor mange sider i sekundet klarer maskinen», «hva er P95 nå»
eller «hvor ofte grep tallvakten inn denne uka» — og uten de svarene kan
ingen bestemme om systemet trenger mer maskinvare eller bare bedre
innstillinger. Det er nettopp den avgjørelsen kapasitetsplanleggingen
står og faller på.

Ingen nye avhengigheter: `prometheus_client` ville vært ett pip-kall,
men prosjektet skal kunne kopieres til en server uten internett
(CLAUDE.md §1), og formatet er en tekstfil med fire regler.

TO TING SOM VILLE ØDELAGT DETTE, OG HVORDAN DE ER STOPPET

  Kardinalitet. `sti="/jobb/9f3c-…"` gir én tidsserie per jobb, og etter
  en uke er minnet fullt av søppel ingen kan spørre på. Stier
  normaliseres derfor til RUTER (`/jobb/{id}`), og ukjente stier samles
  under «annet». Antall serier er dermed begrenset av koden, ikke av
  trafikken.

  Personopplysninger. Ingenting her har et felt der et fødselsnummer,
  et beløp eller et filnavn kan havne. Etikettene er lukkede verdier
  (rute, statuskode, utfall) — aldri innhold. `/metrics` skal kunne
  eksponeres for et overvåkingssystem uten en personvernvurdering, og
  det holder bare hvis det er umulig å få innhold inn hit.

Navnene er norske uten æøå: Prometheus tillater bare [a-zA-Z_:][a-zA-Z0-9_:]*
i metrikknavn, og æøå ville gjort dem ulovlige. Suffiksene `_total` og
`_sekunder` er standard i økosystemet og beholdes (CLAUDE.md §2).
"""
import threading
import time

_las = threading.Lock()
_tellere = {}      # (navn, etiketter) -> float
_maalere = {}      # (navn, etiketter) -> float
_histogram = {}    # (navn, etiketter) -> {"sum": float, "bøtter": [int, ...]}
_start = time.time()

# Latensbøtter i sekunder. Dekker hele spennet vi faktisk har: et
# tekstlags-oppslag på millisekunder, et interaktivt modellsvar på
# sekunder, og en skannet bunke på minutter. P95-målet i
# kapasitetsplanleggingen leses av disse.
BOTTER = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0)

# Rutene vi teller på. Alt annet blir «annet» — se kardinalitet over.
# Rekkefølgen betyr noe: lengste treff først, ellers spiser «/dokument»
# opp «/dokument/operasjoner».
_RUTER = (
    "/dokument/operasjoner", "/dokument", "/forhandssjekk", "/sladd",
    "/ekko", "/spor", "/jobb", "/innsyn", "/hjelp", "/metrics",
    "/dokumentasjon", "/openapi.json",
)

_BESKRIVELSER = {
    "nav_foresporsler_total": ("Forespørsler ferdigbehandlet, per rute og "
                               "HTTP-status", "counter"),
    "nav_foresporsel_sekunder": ("Hvor lang tid en forespørsel tok", "histogram"),
    "nav_ocr_sider_total": ("Sider lest med OCR", "counter"),
    "nav_ocr_sekunder_total": ("Sekunder brukt på OCR", "counter"),
    "nav_modellkall_total": ("Kall til språkmodellen, per utfall", "counter"),
    "nav_modell_sekunder_total": ("Sekunder brukt i språkmodellen", "counter"),
    "nav_tallvakt_total": ("Svar tallvakten var innom, per utfall "
                           "(stoppet/rent)", "counter"),
    "nav_gjennomgang_total": ("Dokumenter sendt til menneskelig "
                              "gjennomgang, per grunn", "counter"),
    # R214 (§30): livssyklusen skal brukes av «API, eventer, adaptere OG
    # observability». De tre første var på plass; her var det et hull —
    # `/metrics` kunne fortelle hvor mange forespørsler som kom inn, men
    # ikke hvor mange jobber som endte i `feil` eller ble stående i
    # `i_ko`. Etiketten er den OFFENTLIGE tilstanden fra
    # `delt/tilstander.py`, så et dashbord og et API-svar bruker samme
    # ord om samme ting.
    "nav_jobb_tilstand_total": ("Tilstandsoverganger for jobber, per "
                                "kanonisk tilstand (delt/tilstander.py)",
                                "counter"),
    # ADR-0007. De to hører sammen: `nav_kapasitet` er hele grensen,
    # `nav_tak_batch` er det jobbarbeidet får bruke, og differansen er
    # den reserverte andelen. Uten dem ser lavere batch-gjennomstrømning
    # ut som en regresjon i stedet for en beslutning.
    "nav_reservert_interaktiv": ("Plasser batch-arbeid aldri får ta "
                                 "(ADR-0007)", "gauge"),
    "nav_tak_batch": ("Hvor mange plasser jobbarbeidet får bruke",
                      "gauge"),
    "nav_i_flukt": ("Tunge forespørsler under behandling akkurat nå", "gauge"),
    "nav_kapasitet": ("Hvor mange tunge forespørsler maskinen slipper inn "
                      "samtidig", "gauge"),
    "nav_kapasitet_binder": ("1 på ressursen som BEGRENSER kapasiteten nå "
                             "(gpu/cpu/ram) — mer av noe annet hjelper "
                             "ikke", "gauge"),
    "nav_vram_ledig_mb": ("Ledig VRAM i MiB", "gauge"),
    "nav_borealis_klar": ("1 når språkmodellen er lastet og svarer", "gauge"),
    "nav_oppetid_sekunder": ("Sekunder siden serveren startet", "gauge"),
}


def rute(sti: str) -> str:
    """Stien normalisert til en RUTE. `/jobb/9f3c-…` blir `/jobb`, og
    alt ukjent blir «annet» — ellers vokser antall tidsserier med
    trafikken i stedet for med koden."""
    sti = (sti or "").split("?", 1)[0]
    for kjent in _RUTER:
        if sti == kjent or sti.startswith(kjent + "/"):
            return kjent
    # /api/v1-prefikset svarer på de samme rutene
    if sti.startswith("/api/v1"):
        return rute(sti[len("/api/v1"):] or "/")
    return "annet"


def _nokkel(navn: str, etiketter: dict):
    return (navn, tuple(sorted((str(k), str(v)) for k, v in
                               (etiketter or {}).items())))


def tell(navn: str, verdi: float = 1.0, **etiketter) -> None:
    """Øk en teller. Tellere går bare oppover og nullstilles ved omstart
    — det er meningen; overvåkingssystemet regner ut raten selv."""
    with _las:
        n = _nokkel(navn, etiketter)
        _tellere[n] = _tellere.get(n, 0.0) + verdi


def sett(navn: str, verdi: float, **etiketter) -> None:
    """Sett en måler (gauge) — en verdi som kan gå begge veier."""
    with _las:
        _maalere[_nokkel(navn, etiketter)] = float(verdi)


def observer(navn: str, sekunder: float, **etiketter) -> None:
    """Legg en varighet i et histogram, så P95 kan regnes ut."""
    with _las:
        n = _nokkel(navn, etiketter)
        h = _histogram.get(n)
        if h is None:
            h = {"sum": 0.0, "antall": 0, "botter": [0] * len(BOTTER)}
            _histogram[n] = h
        h["sum"] += sekunder
        h["antall"] += 1
        for i, grense in enumerate(BOTTER):
            if sekunder <= grense:
                h["botter"][i] += 1


def nullstill() -> None:
    """Bare for tester — en server nullstiller aldri tellerne sine."""
    with _las:
        _tellere.clear()
        _maalere.clear()
        _histogram.clear()


def _etikettekst(etiketter) -> str:
    if not etiketter:
        return ""
    inni = ",".join(f'{k}="{_rens(v)}"' for k, v in etiketter)
    return "{" + inni + "}"


def _rens(verdi: str) -> str:
    """Etikettverdier skal ikke kunne brekke formatet. Ingen anførsel,
    ingen bakoverstrek, ingen linjeskift."""
    return (str(verdi).replace("\\", "").replace('"', "")
            .replace("\n", " ")[:60])


def tekst() -> str:
    """Alt vi måler, i Prometheus' tekstformat."""
    with _las:
        tellere = dict(_tellere)
        maalere = dict(_maalere)
        histogram = {k: {"sum": v["sum"], "antall": v["antall"],
                         "botter": list(v["botter"])}
                     for k, v in _histogram.items()}
    maalere[("nav_oppetid_sekunder", ())] = round(time.time() - _start, 1)

    linjer, sett_hode = [], set()

    def hode(navn, mengde="counter"):
        if navn in sett_hode:
            return
        sett_hode.add(navn)
        hjelp, type_ = _BESKRIVELSER.get(navn, (navn, mengde))
        linjer.append(f"# HELP {navn} {hjelp}")
        linjer.append(f"# TYPE {navn} {type_}")

    for (navn, etiketter), verdi in sorted(tellere.items()):
        hode(navn, "counter")
        linjer.append(f"{navn}{_etikettekst(etiketter)} {verdi:g}")
    for (navn, etiketter), verdi in sorted(maalere.items()):
        hode(navn, "gauge")
        linjer.append(f"{navn}{_etikettekst(etiketter)} {verdi:g}")
    for (navn, etiketter), h in sorted(histogram.items()):
        hode(navn, "histogram")
        lopende = 0
        for i, grense in enumerate(BOTTER):
            lopende = h["botter"][i]
            merke = list(etiketter) + [("le", f"{grense:g}")]
            linjer.append(f"{navn}_bucket{_etikettekst(merke)} {lopende}")
        merke = list(etiketter) + [("le", "+Inf")]
        linjer.append(f"{navn}_bucket{_etikettekst(merke)} {h['antall']}")
        linjer.append(f"{navn}_sum{_etikettekst(etiketter)} {h['sum']:g}")
        linjer.append(f"{navn}_count{_etikettekst(etiketter)} {h['antall']}")
    return "\n".join(linjer) + "\n"
