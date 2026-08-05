"""Oppslag i lovtekstene — med loven ALLTID oppgitt.

Systemet har to folketrygdlover, og de bruker de samme paragrafnumrene
om ulike ting: «§ 8-1» er uførepensjon i 1966-loven og sykepenger i
1997-loven. 18 av kapitlene betyr noe annet i den ene enn i den andre.

Derfor er hovedregelen her: en referanse UTEN lov besvares ikke med et
valg, men med begge tolkningene og beskjed om at den er flertydig. Slår
vi opp i feil lov, får vi et svar som ser helt riktig ut — og et svar
som ser riktig ut, men er hentet fra en opphevet lov, er verre enn
ingen svar.

Registeret over lovene står i `regler/lover.md`; tekstene ligger i
`data/lover/` (for store for git, følger med når mappa kopieres).
"""
import os
import re
from datetime import date

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTER_STI = os.path.join(ROT, "regler", "lover.md")

# [[lov:id]] … [[/lov:id]] med «nøkkel = verdi» inni
_LOVBLOKK = re.compile(
    r"^\[\[lov:([a-zæøå0-9_.\-]+)\]\][ \t]*\r?\n(.*?)\r?\n\[\[/lov:\1\]\]",
    re.DOTALL | re.MULTILINE | re.IGNORECASE)

# «Kapittel 11 A. Tilleggsstønader» / «Kap. 3A.» / «Kap. 4 Dagpenger»:
# bokstaven etter tallet hører til kapittelnummeret bare når det IKKE
# starter et ord — ellers ble «Kap. 4 Dagpenger» til kapittel «4 D».
_KAPITTEL = re.compile(
    r"^###\s+Kap(?:ittel|\.)?\s*(\d+(?:\s?[A-ZÆØÅ](?![a-zæøå]))?)\.?\s*(.*)$")
_PARAGRAF = re.compile(r"^####\s+(§\s*[\w\- ]+?)\.?\s*(?:\.|$|\s{2,})(.*)$")

_bufret = {"mtime": None, "lover": {}}
_tekstbuffer = {}


def _les_register() -> dict:
    """Leser regler/lover.md på nytt når fila er endret."""
    try:
        mtime = os.path.getmtime(REGISTER_STI)
    except OSError as feil:
        raise RuntimeError(
            f"Finner ikke lovregisteret {REGISTER_STI} — uten det vet vi "
            f"ikke hvilke lover som finnes, og et paragrafoppslag kan "
            f"ikke knyttes til riktig lov. ({feil})") from feil
    if _bufret["mtime"] == mtime:
        return _bufret["lover"]
    with open(REGISTER_STI, encoding="utf-8-sig") as f:
        raa = f.read()
    lover = {}
    for lov_id, kropp in _LOVBLOKK.findall(raa):
        felter = {}
        for linje in kropp.splitlines():
            if "=" in linje:
                nokkel, _, verdi = linje.partition("=")
                felter[nokkel.strip()] = verdi.strip()
        felter["id"] = lov_id
        lover[lov_id] = felter
    _bufret.update(mtime=mtime, lover=lover)
    return lover


def lover() -> dict:
    """Alle registrerte lover, id → felter."""
    return _les_register()


def lov(lov_id: str) -> dict:
    """Én lov. KeyError med lista over gyldige id-er hvis den er ukjent."""
    alle = _les_register()
    if lov_id not in alle:
        raise KeyError(
            f"Ukjent lov «{lov_id}». Registrerte lover: "
            f"{', '.join(sorted(alle))}")
    return alle[lov_id]


def _lovtekst(lov_id: str) -> str:
    """Lovteksten, lest én gang per prosess."""
    if lov_id in _tekstbuffer:
        return _tekstbuffer[lov_id]
    sti = os.path.join(ROT, lov(lov_id)["fil"].replace("/", os.sep))
    try:
        with open(sti, encoding="utf-8") as f:
            tekst = f.read()
    except OSError as feil:
        raise RuntimeError(
            f"Lovteksten for «{lov_id}» mangler ({sti}). Hent den med:\n"
            f"  python skript/hent_lovtekst.py {lov(lov_id)['kilde']} "
            f"{lov(lov_id)['fil']}") from feil
    _tekstbuffer[lov_id] = tekst
    return tekst


def kapitler(lov_id: str) -> dict:
    """Kapittelnummer → kapitteltittel. Det er kapitlene som navngir
    ytelsene: i 1997-loven er kapittel 8 sykepenger og kapittel 12
    uføretrygd."""
    ut = {}
    for linje in _lovtekst(lov_id).splitlines():
        treff = _KAPITTEL.match(linje)
        if treff:
            nummer = " ".join(treff.group(1).split())
            ut[nummer] = treff.group(2).strip().rstrip(".")
    return ut


def sok_ytelse(navn: str, lov_id: str = None) -> list:
    """Hvilke kapitler som handler om en ytelse — i ALLE registrerte
    lover, eller i én bestemt.

    Dette er hovedgrunnen til at begge lovene er med: et gammelt vedtak
    om «uførepensjon» hører hjemme i 1966-lovens kapittel 8, mens dagens
    «uføretrygd» står i 1997-lovens kapittel 12. Søker man bare i den
    gjeldende loven, finner man ikke hjemmelen for det gamle vedtaket —
    og søker man uten å skille lovene, blander man dem.

    Hvert treff sier hvilken lov det kom fra og om den er gjeldende."""
    leddet = (navn or "").strip().lower()
    if not leddet:
        return []
    treff = []
    for lid in ([lov_id] if lov_id else sorted(_les_register())):
        meta = lov(lid)
        for nummer, tittel in kapitler(lid).items():
            if leddet in tittel.lower():
                treff.append({
                    "lov": lid,
                    "lov_tittel": meta.get("tittel"),
                    "status": meta.get("status"),
                    "kapittel": nummer,
                    "kapittel_tittel": tittel,
                    "gjelder_fra": meta.get("gjelder_fra"),
                    "gjelder_til": meta.get("gjelder_til") or None,
                })
    # gjeldende rett først — den er som regel den man er ute etter
    treff.sort(key=lambda t: (t["status"] != "gjeldende", t["lov"],
                              t["kapittel"]))
    return treff


def _kapittel_av(paragraf: str):
    """Kapittelnummeret en paragrafreferanse hører til: «§ 8-1» → «8»,
    «§ 11 A-3» → «11 A»."""
    treff = re.search(r"§?\s*(\d+(?:\s?[A-ZÆØÅ](?![a-zæøå]))?)\s*-", paragraf)
    return " ".join(treff.group(1).split()) if treff else None


def normaliser(paragraf: str) -> str:
    """«§8-1», «8-1», «paragraf 8-1» → «§ 8-1»."""
    treff = re.search(r"(\d+(?:\s?[A-ZÆØÅ](?![a-zæøå]))?\s*-\s*\d+\s*[a-z]?)",
                      paragraf or "")
    if not treff:
        return (paragraf or "").strip()
    return "§ " + re.sub(r"\s*-\s*", "-", treff.group(1).strip())


def slaa_opp(paragraf: str, lov_id: str) -> dict:
    """Teksten til én paragraf i EN bestemt lov.

    Returnerer {lov, paragraf, kapittel, kapittel_tittel, tekst,
    funnet}. Finnes ikke paragrafen, er `funnet` False og `tekst` None —
    ikke nærmeste nabo."""
    ref = normaliser(paragraf)
    meta = lov(lov_id)
    kapittel = _kapittel_av(ref)
    svar = {
        "lov": lov_id,
        "lov_tittel": meta.get("tittel"),
        "lov_status": meta.get("status"),
        "paragraf": ref,
        "kapittel": kapittel,
        "kapittel_tittel": kapitler(lov_id).get(kapittel),
        "tekst": None,
        "funnet": False,
    }
    linjer = _lovtekst(lov_id).splitlines()
    # eksakt overskriftstreff: «#### § 8-1. Formål»
    monster = re.compile(r"^####\s+" + re.escape(ref) + r"(?![\d\-])")
    for i, linje in enumerate(linjer):
        if not monster.match(linje):
            continue
        svar["overskrift"] = linje[5:].strip()
        biter = []
        for videre in linjer[i + 1:]:
            if videre.startswith("#"):
                break
            biter.append(videre)
        svar["tekst"] = "\n".join(biter).strip()
        svar["funnet"] = True
        break
    return svar


def lov_for_dato(dokumentdato) -> dict:
    """Hvilken lov som gjaldt på en gitt dato.

    Er datoen ukjent, er svaret ukjent: et vedtak vi ikke kan tidfeste,
    kan ikke knyttes til en bestemt lov uten å gjette — og en gjetning
    om hjemmelen for et vedtak er verre enn ingen."""
    if not dokumentdato:
        return {"lov": None, "begrunnelse":
                "Dokumentdatoen er ukjent, og da kan ikke lovvalget "
                "avgjøres. Oppgi loven eksplisitt."}
    try:
        aar, maaned, dag = (int(x) for x in str(dokumentdato)[:10].split("-"))
        dato = date(aar, maaned, dag)
    except (ValueError, TypeError):
        return {"lov": None, "begrunnelse":
                f"Klarte ikke å lese datoen «{dokumentdato}» (venter "
                f"ISO, åååå-mm-dd)."}
    for lov_id, meta in sorted(_les_register().items()):
        fra = meta.get("gjelder_fra") or "0001-01-01"
        til = meta.get("gjelder_til") or "9999-12-31"
        if fra <= dato.isoformat() < til:
            return {"lov": lov_id, "begrunnelse":
                    f"Dokumentet er datert {dato.isoformat()}, og "
                    f"{meta.get('tittel')} gjaldt fra {fra}"
                    + (f" til {til}" if meta.get("gjelder_til") else "")
                    + "."}
    return {"lov": None, "begrunnelse":
            f"Ingen registrert lov dekker {dato.isoformat()}."}


def tolk_referanse(paragraf: str, lov_id: str = None,
                   dokumentdato=None) -> dict:
    """En paragrafreferanse tolket — med loven avgjort, eller med et
    ærlig «flertydig».

    Er loven ikke oppgitt og dokumentdatoen ukjent, gjetter vi IKKE.
    Svaret lister da hva referansen ville betydd i hver enkelt lov, så
    et menneske kan se forskjellen og velge."""
    ref = normaliser(paragraf)
    if lov_id:
        return {"flertydig": False, "valgt_lov": lov_id,
                "begrunnelse": "Loven ble oppgitt i forespørselen.",
                "treff": [slaa_opp(ref, lov_id)]}

    if dokumentdato:
        valg = lov_for_dato(dokumentdato)
        if valg["lov"]:
            return {"flertydig": False, "valgt_lov": valg["lov"],
                    "begrunnelse": valg["begrunnelse"],
                    "treff": [slaa_opp(ref, valg["lov"])]}

    treff = [slaa_opp(ref, lov_id) for lov_id in sorted(_les_register())]
    funnet = [t for t in treff if t["funnet"]]
    if len(funnet) == 1:
        return {"flertydig": False, "valgt_lov": funnet[0]["lov"],
                "begrunnelse": f"{ref} finnes bare i "
                               f"{funnet[0]['lov_tittel']}.",
                "treff": funnet}
    if not funnet:
        return {"flertydig": False, "valgt_lov": None,
                "begrunnelse": f"{ref} finnes ikke i noen registrert lov.",
                "treff": []}
    kapitler_sett = {(t["lov"], t["kapittel_tittel"]) for t in funnet}
    return {
        "flertydig": True,
        "valgt_lov": None,
        "begrunnelse": (
            f"{ref} finnes i {len(funnet)} lover og betyr ulike ting: "
            + "; ".join(f"{t['lov']} → {t['kapittel_tittel']}"
                        for t in funnet)
            + ". Oppgi lov eller dokumentdato."),
        "treff": funnet,
    }
