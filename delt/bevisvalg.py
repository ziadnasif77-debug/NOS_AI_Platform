"""Bevisvalg: gi modellen de SIDENE spørsmålet gjelder, ikke hele bunken.

Målt problem (Phase 0-rapporten §5): på en 10-siders bunke besvares
spørsmål om side 9–10 fra side 1–3. «Hvilken dato er vedtaket som det
klages på?» ga vedtaksdatoen fra side 1 i stedet for det påklagede
vedtakets dato på side 9.

Det er IKKE avkorting. Dokumentet er 7 176 tegn, godt innenfor
`MAKS_LLM_TEGN`, så modellen så alle sidene. Den skiller bare ikke
dokumentene i bunken fra hverandre — en bunke er ti dokumenter, ikke ett
langt dokument, og modellen behandler den som det siste.

HYPOTESEN SOM MÅLES: mindre og mer relevant kontekst gir mindre
forveksling. Den er ikke opplagt sann — færre sider kan også fjerne
konteksten et riktig svar trengte. Derfor er dette AV som standard til
spørsmålskorpuset har dømt (R148/R189-disiplinen: intervaller, ikke
punkttall).

TRE TING SOM HOLDER DETTE ÆRLIG

  Deterministisk. Poengsettingen er ordoverlapp og entitetstreff —
  ingen modell, ingen embedding, ingen terskler ingen har målt. Samme
  spørsmål og samme dokument gir samme sider, hver gang (R6).

  Aldri tomt. Treffer ingenting, sendes ALT. Et bevisvalg som gir
  modellen ingenting å svare på, er verre enn ingen seleksjon.

  Sier hva som ble utelatt. Utvalget returneres sammen med teksten, så
  svaret kan si «basert på side 9 av 10». Uten det er seleksjon en
  usynlig innsnevring av grunnlaget — nøyaktig den klassen feil
  prosjektet ellers vokter mot.
"""
import re

# Ord som finnes i nesten hvert spørsmål og hvert dokument. De bærer
# ingen informasjon om HVILKEN side som er relevant, og uten denne lista
# ville hver side fått samme poengsum.
_STOPPORD = {
    "og", "i", "på", "det", "som", "til", "er", "av", "en", "et", "for",
    "med", "den", "de", "har", "at", "om", "fra", "kan", "skal", "hva",
    "hvem", "hvor", "hvilken", "hvilke", "hvorfor", "når", "står", "være",
    "dette", "denne", "disse", "seg", "sin", "sitt", "eller", "men", "så",
    "du", "vi", "jeg", "han", "hun", "the", "of", "a", "in", "dokumentet",
    "dokument", "siden", "side", "gjelder", "finnes", "mye", "mange",
}

# Ord som peker på HVA slags opplysning spørsmålet er ute etter. Treffer
# et av dem, vektes sider som inneholder den typen innhold ekstra — det
# er ofte det som skiller to sider som ellers ligner.
_SIGNALORD = {
    "beløp": (r"\d[\d  ]*[,.]\d{2}|\bkr\b|kroner", 2.0),
    "belop": (r"\d[\d  ]*[,.]\d{2}|\bkr\b|kroner", 2.0),
    "dato": (r"\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{4}-\d{2}-\d{2}", 2.0),
    "datert": (r"\d{1,2}[./]\d{1,2}[./]\d{2,4}", 2.0),
    "forfall": (r"forfall", 3.0),
    "konto": (r"kontonummer|konto\b", 3.0),
    "kid": (r"\bkid\b", 3.0),
    "fødselsnummer": (r"f[øo]dselsnummer|\b\d{11}\b", 2.0),
    "telefon": (r"telefon|\+47", 2.0),
    "epost": (r"e-?post|@", 2.0),
    "adresse": (r"\b\d{4}\s+[A-ZÆØÅ]", 2.0),
    "saksnummer": (r"saksnummer|saksnr", 3.0),
    "diagnose": (r"diagnose|icpc", 3.0),
    "klage": (r"klage|klagar", 3.0),
    "renter": (r"rente", 3.0),
    "signatur": (r"signatur|underskrift", 2.0),
    "strekkode": (r"strekkode|barcode", 3.0),
}

_ORD = re.compile(r"[a-zA-ZæøåÆØÅ0-9]{3,}")


def _nokkelord(sporsmal: str) -> set:
    return {o.lower() for o in _ORD.findall(sporsmal or "")
            if o.lower() not in _STOPPORD}


# Korteste felles forstavelse to ord må dele for å regnes som samme
# ord. NORSK BØYNING GJØR DETTE NØDVENDIG: spørsmålet sier «dagsatsen»
# og «returslippen», dokumentet sier «dagsats» og «returslipp». Med
# eksakt delstrengmatch traff ingen av dem, og siden fikk null poeng.
# Fem tegn er valgt fordi kortere gir falske treff («dato» ville
# matchet «datamaskin»), lengre mister «klage»/«klagar» (bokmål mot
# nynorsk — bunken vår har begge).
_FELLES_FORSTAVELSE = 5


def _samme_ord(a: str, b: str) -> bool:
    """Er dette samme ord, bøyning til side?"""
    if a == b:
        return True
    kort, lang = (a, b) if len(a) <= len(b) else (b, a)
    if len(kort) < 4:
        return False          # korte ord må treffe eksakt
    if lang.startswith(kort):
        return True           # «dagsats» i «dagsatsen»
    n = min(len(kort), _FELLES_FORSTAVELSE)
    return len(kort) >= _FELLES_FORSTAVELSE and a[:n] == b[:n]


def poeng_for_side(sidetekst: str, nokkelord: set, sporsmal: str) -> float:
    """Hvor relevant er denne siden for spørsmålet?

    To bidrag: hvor mange av spørsmålets ord som står på siden, og om
    siden inneholder den TYPEN opplysning spørsmålet er ute etter."""
    lav = (sidetekst or "").lower()
    if not lav.strip():
        return 0.0
    sideord = {o.lower() for o in _ORD.findall(lav)}
    poeng = 0.0
    for ord_ in nokkelord:
        if any(_samme_ord(ord_, so) for so in sideord):
            # Et sjeldent ord sier mer enn et vanlig. Lengde er en
            # billig og robust nok proxy for sjeldenhet her — vi har
            # ingen korpusstatistikk å regne IDF av, og å late som vi
            # har det ville vært verre enn å bruke noe enkelt.
            poeng += 1.0 + min(len(ord_), 12) / 12.0
    lav_sp = (sporsmal or "").lower()
    for signal, (monster, vekt) in _SIGNALORD.items():
        if signal in lav_sp and re.search(monster, lav, re.IGNORECASE):
            poeng += vekt
    return round(poeng, 3)


def velg_sider(sider: dict, sporsmal: str, maks_sider: int = 3,
               minste_poeng: float = 1.5) -> dict:
    """Hvilke sider skal modellen få se?

    Returnerer {valgte, utelatte, poeng, alle} — `valgte` tom betyr at
    kalleren skal sende ALT. Det er ikke en feil: treffer ingenting, er
    hele dokumentet det ærligste grunnlaget."""
    nokkelord = _nokkelord(sporsmal)
    if not sider or not nokkelord:
        return {"valgte": [], "utelatte": [], "poeng": {}, "alle": True,
                "grunn": "ingen nøkkelord i spørsmålet"}
    poeng = {nr: poeng_for_side(tekst, nokkelord, sporsmal)
             for nr, tekst in sider.items()}
    over = sorted((nr for nr, p in poeng.items() if p >= minste_poeng),
                  key=lambda nr: (-poeng[nr], nr))
    if not over:
        return {"valgte": [], "utelatte": [], "poeng": poeng, "alle": True,
                "grunn": "ingen side skilte seg ut"}
    # Alle sider like relevante? Da har seleksjonen ingenting å bidra
    # med, og å velge tre av ti ville vært vilkårlig.
    if len(over) == len(sider):
        return {"valgte": [], "utelatte": [], "poeng": poeng, "alle": True,
                "grunn": "alle sider er like relevante"}
    valgte = sorted(over[:maks_sider])
    return {"valgte": valgte,
            "utelatte": sorted(nr for nr in sider if nr not in valgte),
            "poeng": poeng, "alle": False,
            "grunn": f"{len(valgte)} av {len(sider)} sider valgt på "
                     "ordoverlapp og innholdstype"}


def bygg_utvalgstekst(sider: dict, valgte: list, antall_sider: int) -> str:
    """Teksten modellen får, med sidemarkørene beholdt.

    Markørene er ikke pynt: uten dem mister modellen den ENE opplysningen
    som lar den skille dokumentene i bunken fra hverandre — og det er
    nettopp forvekslingen vi prøver å fjerne."""
    biter = []
    for nr in valgte:
        biter.append(f"[Side {nr} av {antall_sider}]\n{sider.get(nr, '')}")
    return "\n\n".join(biter)
