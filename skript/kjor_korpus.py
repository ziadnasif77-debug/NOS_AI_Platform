"""
Kjører regresjonskorpuset: ekte dokumenter mot en fasit skrevet av et
menneske, og rapporterer treffprosent i stedet for magefølelse.

Bakgrunn (R60): systemet ble lenge forbedret ett dokument om gangen —
noen møtte et problem, vi målte, vi fikset. Det gir gode enkeltfikser,
men ingen oversikt: vi visste aldri om en endring hjalp på ÉN fil og
skadet fem andre. To ganger ble ytelsen dessuten finjustert mot
syntetiske testbilder som ikke lignet virkeligheten.

Korpuset gjør «virker det?» om fra en mening til et tall.

Slik brukes det:
    python skript/kjor_korpus.py                    # kjør alt
    python skript/kjor_korpus.py syntetisk_bunke    # navnefilter

Korpuset inneholder KUN syntetiske dokumenter (se tester/korpus/README.md
— fasitene ligger i git, så ekte verdier ville blitt liggende i
historikken for alltid).

Fasitene ligger i tester/korpus/*.json og ER versjonert — de definerer
hva «riktig» betyr. Selve dokumentene ligger i data/korpus/ (utenfor
git, som resten av data/). Mangler en fil, hoppes den over med beskjed
i stedet for å felle kjøringen.

Se tester/korpus/README.md for hvordan du legger til et dokument.
"""
import json
import os
import sys
import time

# UTF-8-trygg utskrift (se finjuster.py): norsk (æøå) skal ikke krasje når
# stdout er en pipe/fil med cp1256 (f.eks. i CI eller omdirigert til logg).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)

FASIT_MAPPE = os.path.join(ROT, "tester", "korpus")
DOKUMENT_MAPPE = os.path.join(ROT, "data", "korpus")
BASE = os.environ.get("KORPUS_API", "http://127.0.0.1:8600")


def _api_nokkel() -> str:
    """API-nøkkelen fra miljøet, eller fra .env i prosjektroten.

    Korpuskjøreren ble skrevet før serveren håndhevet X-API-Key, og
    stoppet på 401 over hele linja da nøkkelen kom — regresjonsPORTEN
    var dermed selv regressert. Leser .env direkte (uten avhengigheter)
    så «python skript/kjor_korpus.py» bare virker."""
    nokkel = os.environ.get("API_NOKKEL", "")
    if nokkel:
        return nokkel
    try:
        with open(os.path.join(ROT, ".env"), encoding="utf-8") as f:
            for linje in f:
                linje = linje.strip()
                if linje.startswith("API_NOKKEL="):
                    return linje.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def hent_sti(data, sti: str):
    """Slår opp «belop.0.verdi» i et nøstet svar. Returnerer en
    sentinel når stien ikke finnes, slik at «manglende» og «None» ikke
    blandes sammen."""
    naa = data
    for ledd in sti.split("."):
        if isinstance(naa, list):
            try:
                naa = naa[int(ledd)]
            except (ValueError, IndexError):
                return MANGLER
        elif isinstance(naa, dict):
            if ledd not in naa:
                return MANGLER
            naa = naa[ledd]
        else:
            return MANGLER
    return naa


MANGLER = object()


def sammenlign(forventet, faktisk) -> bool:
    """Tall sammenlignes med liten toleranse; datoer og tekst ordrett.
    En dato som ligger i en liste av dict-er (klassifiserte datoer)
    aksepteres både som streng og som {"dato": ...}."""
    if faktisk is MANGLER:
        return False
    if isinstance(faktisk, dict) and "dato" in faktisk:
        faktisk = faktisk["dato"]
    if isinstance(forventet, (int, float)) and isinstance(faktisk, (int, float)):
        return abs(float(forventet) - float(faktisk)) < 0.005
    return forventet == faktisk


def kjor_ett(fasit: dict) -> dict:
    """Kjører ett dokument og returnerer {bestatt, feilet, detaljer}."""
    import requests

    sti = os.path.join(DOKUMENT_MAPPE, fasit["fil"])
    if not os.path.isfile(sti):
        return {"hoppet_over": "finner ikke %s" % sti}

    with open(sti, "rb") as f:
        t0 = time.perf_counter()
        try:
            # Hovedveien (/dokument) med struktur=ja: fasitene kan da
            # sjekke BÅDE entallsfeltene (felter.felter.*) og de komplette
            # listene (struktur.identifikatorer.*) i samme svar.
            svar = requests.post(BASE + "/dokument",
                                 files={"fil": (fasit["fil"], f,
                                                "application/pdf")},
                                 data={"struktur": "ja"},
                                 headers={"X-API-Key": _api_nokkel()},
                                 timeout=900)
        except Exception as exc:
            return {"feil": "kom ikke til serveren: %s" % exc}
        brukt = time.perf_counter() - t0

    if svar.status_code != 200:
        return {"feil": "HTTP %d: %s" % (svar.status_code, svar.text[:200])}
    data = svar.json()

    bestatt, feilet = [], []

    for sti_uttrykk, forventet in (fasit.get("felter") or {}).items():
        faktisk = hent_sti(data, sti_uttrykk)
        if sammenlign(forventet, faktisk):
            bestatt.append(sti_uttrykk)
        else:
            vist = "(mangler)" if faktisk is MANGLER else repr(faktisk)
            feilet.append("%s: ventet %r, fikk %s"
                          % (sti_uttrykk, forventet, vist))

    # Delmengde-sjekk for lister: fasiten krever at verdiene FINNES, uten
    # å låse hele lista (rekkefølge/støy i OCR skal ikke felle en sjekk
    # på noe annet enn det den faktisk gjelder).
    for sti_uttrykk, forventede in (fasit.get("felter_maa_inneholde")
                                    or {}).items():
        faktisk = hent_sti(data, sti_uttrykk)
        if not isinstance(faktisk, list):
            vist = "(mangler)" if faktisk is MANGLER else repr(faktisk)
            feilet.append("%s: ventet en liste, fikk %s"
                          % (sti_uttrykk, vist))
            continue
        for v in forventede:
            if v in faktisk:
                bestatt.append("%s inneholder %r" % (sti_uttrykk, v))
            else:
                feilet.append("%s mangler %r (fikk %r)"
                              % (sti_uttrykk, v, faktisk))

    tekst = ""
    for kandidat in ("tekst", "raatekst"):
        if isinstance(data.get(kandidat), str):
            tekst = data[kandidat]
            break
    if not tekst:
        tekst = json.dumps(data, ensure_ascii=False)
    for bit in fasit.get("tekst_maa_inneholde") or []:
        if bit in tekst:
            bestatt.append("tekst inneholder %r" % bit)
        else:
            feilet.append("tekst mangler %r" % bit)
    # Negativ sjekk: tekst som IKKE skal finnes — vokter mot at OCR
    # dikter innhold på (nesten) tomme sider.
    for bit in fasit.get("tekst_maa_ikke_inneholde") or []:
        if bit not in tekst:
            bestatt.append("tekst er fri for %r" % bit)
        else:
            feilet.append("tekst inneholder %r — skal ikke finnes" % bit)

    # Tiden rapporteres, men felles ikke kjøringen: analysecachen svarer
    # på millisekunder når samme fil er kjørt før, og en grense som
    # «består» fordi svaret kom fra cache måler ingenting. Ytelse hører
    # hjemme i egne målinger mot en fersk server — korpuset er til for
    # RIKTIGHET.
    tak = fasit.get("maks_sekunder")
    treg = tak is not None and brukt > tak

    return {"bestatt": bestatt, "feilet": feilet, "sekunder": brukt,
            "treg": treg, "tak": tak,
            "svakheter": fasit.get("kjent_svakhet") or {}}


def main() -> int:
    if not os.path.isdir(FASIT_MAPPE):
        print("Fant ingen fasitmappe: %s" % FASIT_MAPPE)
        return 1

    filtre = [a.lower() for a in sys.argv[1:]]
    fasiter = []
    for navn in sorted(os.listdir(FASIT_MAPPE)):
        if not navn.endswith(".json"):
            continue
        if filtre and not any(f in navn.lower() for f in filtre):
            continue
        with open(os.path.join(FASIT_MAPPE, navn), encoding="utf-8") as f:
            fasiter.append((navn[:-5], json.load(f)))

    if not fasiter:
        print("Ingen fasiter å kjøre.")
        return 1

    print("=" * 68)
    print("  REGRESJONSKORPUS — %d dokument(er) mot %s" % (len(fasiter), BASE))
    print("=" * 68)

    sum_bestatt = sum_feilet = 0
    hoppet, svakheter = [], []

    for navn, fasit in fasiter:
        res = kjor_ett(fasit)
        if "hoppet_over" in res:
            hoppet.append("%s (%s)" % (navn, res["hoppet_over"]))
            continue
        if "feil" in res:
            print("\n%-24s KJØRTE IKKE: %s" % (navn, res["feil"]))
            sum_feilet += 1
            continue

        b, f = len(res["bestatt"]), len(res["feilet"])
        sum_bestatt += b
        sum_feilet += f
        merke = "OK " if f == 0 else "AVVIK"
        tid = "%.1fs" % res["sekunder"]
        if res["sekunder"] < 0.2:
            tid += " (fra cache)"
        elif res.get("treg"):
            tid += " — over taket på %.0fs" % res["tak"]
        print("\n%-24s %s  %d/%d sjekker  (%s)"
              % (navn, merke, b, b + f, tid))
        for linje in res["feilet"]:
            print("    ✗ %s" % linje)
        for felt, forklaring in res["svakheter"].items():
            svakheter.append("%s → %s: %s" % (navn, felt, forklaring))

    total = sum_bestatt + sum_feilet
    print("\n" + "=" * 68)
    if total:
        print("  RESULTAT: %d av %d sjekker bestått (%.0f %%)"
              % (sum_bestatt, total, 100 * sum_bestatt / total))
    for linje in hoppet:
        print("  hoppet over: %s" % linje)

    if svakheter:
        print("\n  KJENTE SVAKHETER (dokumentert, ikke regnet som feil):")
        for linje in svakheter:
            print("    · %s" % linje)

    print("=" * 68)
    return 0 if sum_feilet == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
