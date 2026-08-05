"""
Henter en komplett lovtekst fra Lovdata og lagrer alle kapitler og
paragrafer strukturert i én Markdown-fil.

GENERELT verktøy — virker for enhver lov på lovdata.no, ikke én
bestemt: gi hoveddokument-URL-en, så finner skriptet kapitlene selv.

Bruk (fra D:\\nav):
    python skript/hent_lovtekst.py <lovdata-url> [utfil]

Eksempel:
    python skript/hent_lovtekst.py https://lovdata.no/dokument/NLO/lov/1966-06-17-12 "data/lover/Lov om folketrygd.md"

Uten utfil brukes data/lover/<lovens tittel>.md. Skriptet venter et
halvt sekund mellom kapitlene av høflighet mot lovdata.no.
"""
import io
import os
import re
import sys
import time
from datetime import date
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HODER = {"User-Agent": "NAV-arkivprosjekt (lokal referansehenting)"}


def _hent(url: str) -> BeautifulSoup:
    svar = requests.get(url, headers=HODER, timeout=30)
    svar.raise_for_status()
    return BeautifulSoup(svar.text, "html.parser")


def _ren_tekst(element) -> str:
    """Tekst med normaliserte mellomrom, avsnitt skilt med linjeskift."""
    deler = []
    for avsnitt in element.find_all(["p", "h3", "h4", "li"]):
        t = " ".join(avsnitt.get_text(" ", strip=True).split())
        if t:
            deler.append(t)
    if not deler:
        t = " ".join(element.get_text(" ", strip=True).split())
        return t
    return "\n".join(deler)


def _er_lovnode(tag) -> bool:
    """Er dette en overskrift eller en paragraf som hører til LOVEN?

    Sidene har også overskrifter som ikke er lovtekst («Hovedmeny»,
    «Trenger du brukerveiledning?»). Lovens egne står alltid inne i et
    element med id «KAPITTEL_…» — det skillet er tydeligere enn å
    gjette på klassenavn."""
    if str(tag.get("id", "")).startswith("PARAGRAF_"):
        return True
    if tag.name not in ("h2", "h3"):
        return False
    return any(str(f.get("id", "")).startswith("KAPITTEL_")
               for f in tag.parents)


def _overskriftsnivaa(navn: str):
    """Hvilket NIVÅ en overskrift er, avgjort av teksten — ikke av
    HTML-taggen.

    De to folketrygdlovene bruker taggene ulikt: i 1997-loven er h2 en
    «Del» og h3 et «Kapittel», mens 1966-loven ikke har deler i det hele
    tatt og bruker h3 til selve paragrafene. Mapper vi på tagg, blir 245
    paragrafer til «kapitler» i den gamle loven. Teksten sier det samme
    i begge: «Del …», «Kapittel …»/«Kap. …», «§ …».

    Returnerer «##» (del), «###» (kapittel), «*» (underoverskrift) eller
    None for en paragrafoverskrift, som håndteres for seg."""
    if re.match(r"^Del\s+[IVXLC0-9]", navn, re.IGNORECASE):
        return "##"
    if re.match(r"^Kap(?:ittel|\.)?\s*[0-9IVXLC]", navn, re.IGNORECASE):
        return "###"
    if navn.lstrip().startswith("§"):
        return None
    return "*"                 # mellomoverskrift inne i et kapittel


def _rens_navn(navn: str) -> str:
    """Fjerner usynlige fotnotemarkører (zero-width space + tall) fra
    kapittel- og paragrafnavn."""
    navn = re.sub(r"​+\s*\d*", "", navn)
    return " ".join(navn.split())


def hent_lov(url: str, utfil: str = None) -> str:
    print(f"Henter oversikt: {url}")
    oversikt = _hent(url)

    # Lovens tittel: <title>-taggen er påliteligst («... - Lovdata»)
    tittel = "Ukjent lov"
    if oversikt.title and oversikt.title.string:
        tittel = oversikt.title.string.replace("- Lovdata", "").strip()
        tittel = " ".join(tittel.split())

    # Alle kapittellenker i rekkefølge, uten duplikater
    kapittel_urler = []
    sett = set()
    for lenke in oversikt.find_all("a", href=True):
        href = lenke["href"].split("#")[0]
        if re.search(r"/KAPITTEL_[\w-]+$", href) and href not in sett:
            sett.add(href)
            kapittel_urler.append(urljoin(url, href))
    print(f"Lov: {tittel}")
    print(f"Fant {len(kapittel_urler)} kapitler")

    linjer = [f"# {tittel}", "",
              f"Kilde: {url}",
              f"Hentet: {date.today().isoformat()}"]
    if "/NLO/" in url:
        linjer.append("Merk: NLO-registeret hos Lovdata inneholder "
                      "OPPHEVEDE lover — dette er en historisk lovtekst.")
    linjer.append("")

    antall_paragrafer = 0
    sette_paragrafer = set()   # §-id-er på tvers av sider (mot duplikater)
    sette_overskrifter = set()  # samme del/kapittel spenner flere delsider
    for kap_url in kapittel_urler:
        side = _hent(kap_url)
        artikkel = side.find("article") or side

        # Fotnote-opphøyninger fjernes før tekstuttrekk
        for sup in artikkel.find_all("sup"):
            sup.extract()

        nye = 0
        siste_kapittel = None
        # Del, kapittel og paragraf i DOKUMENTREKKEFØLGE. Nivåene må
        # skilles: URL-ene («KAPITTEL_4-3») er en dokumenttre-sti, ikke
        # lovens kapittelnummer — den siden inneholder faktisk kapittel
        # 7. Og kapittelnummeret er nettopp det som navngir ytelsen
        # (kap. 8 sykepenger, 11 arbeidsavklaringspenger, 12 uføretrygd),
        # så det kan ikke gå tapt.
        for el in artikkel.find_all(_er_lovnode):
            if el.name in ("h2", "h3"):
                navn = _rens_navn(el.get_text(" ", strip=True))
                if not navn or navn in sette_overskrifter:
                    continue
                nivaa = _overskriftsnivaa(navn)
                if nivaa is None:        # paragrafoverskrift — tas nedenfor
                    continue
                sette_overskrifter.add(navn)
                # mellomoverskrifter beholdes som uthevet tekst: de sier
                # noe, men de er ikke kapitler og skal ikke telle som det
                linjer += [f"**{navn}**" if nivaa == "*"
                           else f"{nivaa} {navn}", ""]
                if nivaa == "###":
                    siste_kapittel = navn
                continue

            pid = el.get("id")
            hode = el.find(class_=re.compile(r"paragrafhode|paragrafHeader"))
            if hode is None or pid in sette_paragrafer:
                continue
            sette_paragrafer.add(pid)
            para_navn = _rens_navn(hode.get_text(" ", strip=True))
            hode_foreldre = hode.find_parent(["h3", "h4"]) or hode
            hode_foreldre.extract()
            tekst = _ren_tekst(el).replace("​", "")
            linjer += [f"#### {para_navn}", "", tekst, ""]
            antall_paragrafer += 1
            nye += 1
        print(f"  {siste_kapittel or kap_url.rsplit('/', 1)[-1]}: "
              f"{nye} nye paragrafer")
        time.sleep(0.5)

    if utfil is None:
        trygt_navn = re.sub(r"[^\wæøåÆØÅ .-]", "", tittel)[:80].strip()
        utfil = os.path.join(ROT, "data", "lover", f"{trygt_navn}.md")
    os.makedirs(os.path.dirname(utfil), exist_ok=True)
    with open(utfil, "w", encoding="utf-8") as f:
        f.write("\n".join(linjer))
    print(f"\nLagret {antall_paragrafer} paragrafer i {len(kapittel_urler)} "
          f"kapitler til:\n  {utfil}")
    return utfil


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Bruk: python skript/hent_lovtekst.py <lovdata-url> [utfil]')
        sys.exit(1)
    hent_lov(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
