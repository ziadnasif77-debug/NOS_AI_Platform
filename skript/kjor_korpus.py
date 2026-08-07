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
    # R146: TRE utfall, ikke to. «Feltet mangler» og «feltet er galt» er
    # ikke samme feil:
    #
    #   mangler  →  saksbehandleren SER tomrommet og fyller det selv
    #   galt     →  saksbehandleren ser en verdi og bygger et vedtak
    #               på den
    #
    # Slått sammen i én «feilet»-bøtte kunne et korpus gå fra 10 tomme
    # felter til 10 GALE verdier uten at tallet rørte seg. Utfallene
    # skilles nå, og presisjon/recall regnes PER FELT — et snitt over
    # `fodselsnummer` og `kontornavn` skjuler nettopp det som betyr noe.
    utfall = []          # (feltsti, "riktig" | "mangler" | "galt")

    for sti_uttrykk, forventet in (fasit.get("felter") or {}).items():
        faktisk = hent_sti(data, sti_uttrykk)
        if sammenlign(forventet, faktisk):
            bestatt.append(sti_uttrykk)
            utfall.append((sti_uttrykk, "riktig"))
        elif faktisk is MANGLER or faktisk in (None, "", [], {}):
            # Ikke uttrukket. Vi vet at verdien FINNES, for fasiten sier
            # det — dette er et hull, ikke en påstand.
            feilet.append("%s: MANGLER (ventet %r)" % (sti_uttrykk, forventet))
            utfall.append((sti_uttrykk, "mangler"))
        else:
            feilet.append("%s: GALT — ventet %r, fikk %r"
                          % (sti_uttrykk, forventet, faktisk))
            utfall.append((sti_uttrykk, "galt"))

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
                utfall.append((sti_uttrykk, "riktig"))
            else:
                # En verdi som skulle stått i lista og ikke gjør det, er
                # et hull — ikke en gal påstand. De andre verdiene i
                # lista kan godt være riktige.
                feilet.append("%s MANGLER %r (fikk %r)"
                              % (sti_uttrykk, v, faktisk))
                utfall.append((sti_uttrykk, "mangler"))

    # ANTALL i stedet for verdier (R146). En fasit på GitHub kan ikke
    # liste fødselsnummer og kontonummer: elleve siffer i en fil ser ut
    # som et ekte nummer uansett hvor syntetisk det er ment å være, og
    # den som leser repoet kjenner ikke opprinnelsen.
    #
    # Fasiten sa derfor `['12345678910', '12345678910']` — den
    # dokumenterte plassholderen, TO ganger, for både fnr og konto. Den
    # ble aldri fylt ut, og hver kjøring meldte fire manglende verdier
    # for noe dokumentet aldri inneholdt. Det den EGENTLIG ville si var
    # «bunken gjelder to personer, og begge skal finnes».
    for sti_uttrykk, antall in (fasit.get("felter_antall") or {}).items():
        faktisk = hent_sti(data, sti_uttrykk)
        if not isinstance(faktisk, list):
            vist = "(mangler)" if faktisk is MANGLER else repr(faktisk)
            feilet.append("%s: ventet en liste med %d, fikk %s"
                          % (sti_uttrykk, antall, vist))
            utfall.append((sti_uttrykk, "mangler"))
        elif len(faktisk) == antall:
            bestatt.append("%s har %d" % (sti_uttrykk, antall))
            utfall.append((sti_uttrykk, "riktig"))
        elif len(faktisk) < antall:
            feilet.append("%s: MANGLER — ventet %d, fant %d"
                          % (sti_uttrykk, antall, len(faktisk)))
            utfall.append((sti_uttrykk, "mangler"))
        else:
            # Flere enn ventet er en PÅSTAND for mye: noe er lest som en
            # identifikator uten å være det.
            feilet.append("%s: GALT — ventet %d, fant %d (%r)"
                          % (sti_uttrykk, antall, len(faktisk), faktisk))
            utfall.append((sti_uttrykk, "galt"))

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
            "treg": treg, "tak": tak, "utfall": utfall,
            "svakheter": fasit.get("kjent_svakhet") or {}}


def presisjon_og_recall(utfall) -> dict:
    """{feltsti: {riktig, mangler, galt, presisjon, recall}} (R146).

        presisjon = riktig / (riktig + galt)
                    «når jeg svarer, hvor ofte har jeg rett?»
        recall    = riktig / (riktig + galt + mangler)
                    «hvor mye av det som fantes, fikk jeg tak i?»

    Presisjon er `None` når feltet aldri ble besvart — «0 av 0 riktige»
    er ikke 0 %, det er fravær av data. Å skrive 0.0 der ville felt et
    felt vi ikke har målt.

    Regnes PER FELT med vilje. `fodselsnummer` og `kontornavn` har helt
    ulike risikoprofiler, og et snitt over dem forteller ingenting om
    noen av dem."""
    per_felt = {}
    for sti_uttrykk, hva in utfall:
        rad = per_felt.setdefault(sti_uttrykk,
                                  {"riktig": 0, "mangler": 0, "galt": 0})
        rad[hva] += 1
    for rad in per_felt.values():
        svart = rad["riktig"] + rad["galt"]
        alt = svart + rad["mangler"]
        rad["presisjon"] = (rad["riktig"] / svart) if svart else None
        rad["recall"] = (rad["riktig"] / alt) if alt else None
    return per_felt


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
    alle_utfall = []

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
        alle_utfall.extend(res.get("utfall") or [])
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

    # R146: presisjon/recall PER FELT. Den samlede prosenten over sier
    # ingenting om HVILKEN feil vi har — og et korpus kan gå fra ti
    # tomme felter til ti GALE verdier uten at tallet rører seg.
    per_felt = presisjon_og_recall(alle_utfall)
    if per_felt:
        galt_totalt = sum(r["galt"] for r in per_felt.values())
        mangler_totalt = sum(r["mangler"] for r in per_felt.values())
        print("\n  UTFALL: %d riktige · %d MANGLER · %d GALE"
              % (sum(r["riktig"] for r in per_felt.values()),
                 mangler_totalt, galt_totalt))
        print("          (et tomt felt fyller en saksbehandler selv —")
        print("           en gal verdi bygger hen et vedtak på)")
        print("\n  %-42s %6s %6s %5s %5s %5s"
              % ("felt", "presis", "recall", "rett", "mngl", "galt"))
        print("  " + "-" * 66)

        def _sorter(rad):
            # verst først: gale verdier, så manglende
            return (-rad[1]["galt"], -rad[1]["mangler"], rad[0])

        for sti_uttrykk, rad in sorted(per_felt.items(), key=_sorter):
            p = "  —  " if rad["presisjon"] is None else "%5.2f" % rad["presisjon"]
            r = "  —  " if rad["recall"] is None else "%5.2f" % rad["recall"]
            merke = ""
            if rad["galt"]:
                merke = "  ← GALE VERDIER"
            print("  %-42s %6s %6s %5d %5d %5d%s"
                  % (sti_uttrykk[:42], p, r,
                     rad["riktig"], rad["mangler"], rad["galt"], merke))
        if galt_totalt:
            print("\n  %d GALE VERDIER — det er den alvorlige kategorien."
                  % galt_totalt)
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
