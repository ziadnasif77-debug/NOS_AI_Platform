"""
Kalibreringsrapport: BETYR konfidenstallet noe?

    .pyruntime\\python.exe skript\\kalibreringsrapport.py

Serveren sender et dokument til menneskelig gjennomgang når
OCR-konfidensen er under 0.85. Ingen har kunnet svare på om det tallet
betyr noe — og en terskel ingen har målt er en gjetning som har fått
status som regel (R149).

Mekanismen for å måle det ble bygget: `KALIBRERING_ANDEL` sender en
liten andel av de GODT LESTE dokumentene til gjennomgang også, så de
øverste bøttene i tabellen kan fylles. Regnestykket ble bygget
(`delt/kalibrering.py`). Men INGENTING leste dataene og produserte
svaret — innsamlingen hadde ingen vei ut, og spørsmålet kunne fortsatt
ikke besvares. Det er hullet dette skriptet lukker (R197).

HVOR FASITEN KOMMER FRA
Label Studio-oppgaven bærer både konfidensen systemet oppga og den rå
teksten det leste. Mennesket leverer den rettede teksten. Sammenligner
vi de to, vet vi om lesingen VAR riktig — og vi har paret
(oppgitt konfidens, faktisk riktig) som hele kalibreringen hviler på.

Ingenting av dette leser tilgangsloggen: den har konfidensen, men ikke
fasiten, og den mangler nøkkelen som kunne koblet de to. Å legge
dokument-id i en logg for å få den koblingen ville vært en
personvernkostnad for noe Label Studio allerede har.
"""
import os
import sys

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "skript"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                               # noqa: BLE001
    pass

from delt import kalibrering                                    # noqa: E402

# Hvor mye rettingen kan avvike fra den rå lesingen og fortsatt regnes
# som «riktig lest». Ikke null: en annotatør retter ofte et mellomrom
# eller en bindestrek uten at lesingen var gal, og en fasit som
# straffer det måler annotatørvaner, ikke OCR-kvalitet.
GODTATT_AVVIK = float(os.environ.get("KALIBRERING_GODTATT_CER", "0.02"))


def var_riktig(raa: str, rettet: str) -> bool:
    """Var lesingen riktig, eller rettet mennesket en ekte feil?

    Rettinger som BARE gjelder mellomrom teller ikke som feil. Label
    Studio-rettingene er per REGION, altså korte biter — på en linje på
    18 tegn er ett mellomrom 5,6 % tegnfeilrate, og en fasit som
    straffer det måler annotatørvaner i stedet for OCR-kvalitet. Enhver
    ANNEN endring måles med tegnfeilrate som før."""
    if "".join((raa or "").split()) == "".join((rettet or "").split()):
        return bool((rettet or "").strip())
    return _cer(raa, rettet) <= GODTATT_AVVIK


def _cer(a: str, b: str) -> float:
    """Tegnfeilrate mellom rå lesing og rettet tekst (Levenshtein/lengde)."""
    a, b = (a or "").strip(), (b or "").strip()
    if not b:
        return 1.0 if a else 0.0
    forrige = list(range(len(b) + 1))
    for i, tegn_a in enumerate(a, 1):
        naa = [i]
        for j, tegn_b in enumerate(b, 1):
            naa.append(min(forrige[j] + 1, naa[j - 1] + 1,
                           forrige[j - 1] + (tegn_a != tegn_b)))
        forrige = naa
    return forrige[-1] / max(1, len(b))


def hent_par(prosjekt_id: int = None) -> tuple:
    """[(konfidens, var_riktig), …] fra ferdig annoterte oppgaver.

    Returnerer (par, hoppet_over) — det siste er oppgaver som ikke kan
    brukes, med grunn. De TELLES, for et datasett som stille mister
    halvparten av observasjonene gir en tabell som ser solid ut."""
    import eksporter_fra_label_studio as eks
    if prosjekt_id is None:
        prosjekt_id = int(os.environ.get("LABEL_STUDIO_OCR_PROSJEKT_ID", "1"))
    oppgaver = eks.hent_fullforte_oppgaver(prosjekt_id)
    par, hoppet = [], {}

    def _hopp(grunn):
        hoppet[grunn] = hoppet.get(grunn, 0) + 1

    for oppgave in oppgaver:
        data = oppgave.get("data") or {}
        konf = data.get("konfidens")
        raa = data.get("tekst")
        if konf is None:
            _hopp("oppgaven mangler konfidens (sendt før R149?)")
            continue
        rettet = eks.konverter_til_trocr_format(oppgave)
        if not rettet:
            _hopp("ingen brukbar retting (tom eller ikke annotert)")
            continue
        try:
            # Label Studio lagrer konfidensen i prosent (R149-sendingen
            # ganger med 100); tabellen regner i 0–1.
            konfidens = float(konf) / 100.0
        except (TypeError, ValueError):
            _hopp("ukjent konfidensformat")
            continue
        if not 0.0 <= konfidens <= 1.0:
            _hopp("konfidens utenfor 0–1")
            continue
        par.append((konfidens, var_riktig(raa, rettet["tekst"])))
    return par, hoppet


def skriv_rapport(par, hoppet) -> int:
    print("\n" + "=" * 66)
    print("  KALIBRERING — betyr OCR-konfidensen noe?")
    print("=" * 66)
    if not par:
        print("\n  Ingen brukbare observasjoner ennå.")
        for grunn, antall in sorted(hoppet.items()):
            print(f"    {antall:>4}  {grunn}")
        print("\n  Slik fyller du tabellen:")
        print("    1. Sett KALIBRERING_ANDEL=0.02 i .env (gjort?)")
        print("    2. La serveren og Label Studio kjøre noen uker")
        print("    3. Rett dokumentene som havner i Label Studio")
        print("    4. Kjør dette skriptet igjen")
        return 1

    tabell = kalibrering.kalibreringstabell(par)
    ece = kalibrering.ece(par)
    overmodige = kalibrering.overmodig(par)

    print(f"\n  {len(par)} dokumenter med både konfidens og menneskelig fasit")
    if hoppet:
        print("  Hoppet over:")
        for grunn, antall in sorted(hoppet.items()):
            print(f"    {antall:>4}  {grunn}")
    print()
    print(f"  {'Bøtte':<12}{'Antall':>8}{'Oppgitt':>10}{'Faktisk':>10}{'Avvik':>9}")
    for rad in tabell:
        merke = "  ← overmodig" if rad["avvik"] < -0.05 else ""
        print(f"  {rad['botte']:<12}{rad['antall']:>8}{rad['oppgitt']:>10.3f}"
              f"{rad['faktisk']:>10.3f}{rad['avvik']:>9.3f}{merke}")
    print()
    print(f"  ECE (forventet kalibreringsfeil): {ece:.4f}")
    if ece < 0.05:
        print("       < 0.05 — konfidensen er godt kalibrert.")
    elif ece > 0.15:
        print("       > 0.15 — konfidensen sier lite om hva som er riktig.")
        print("       Da er terskelen 0.85 i praksis vilkårlig.")
    else:
        print("       Mellom 0.05 og 0.15 — brukbar, men ikke presis.")

    if overmodige:
        print("\n  OVERMODIGE BØTTER (systemet er sikrere enn det har grunn til):")
        for rad in overmodige:
            print(f"    {rad['botte']}: oppgitt {rad['oppgitt']:.3f}, "
                  f"faktisk {rad['faktisk']:.3f} ({rad['antall']} dok)")
        print("    Dette er den farlige retningen: dokumenter som slipper")
        print("    forbi terskelen uten at noen ser dem.")

    # Det ADR-0004 venter på
    print("\n  " + "-" * 62)
    nok_data = len(par) >= 30 and len(tabell) >= 3
    if nok_data and ece < 0.05:
        print("  ADR-0004 (mellombåndet i gjennomgangsrutingen) kan nå")
        print("  vurderes: konfidensen er kalibrert, så et bånd kan legges")
        print("  der målingen viser at det er trygt.")
    elif not nok_data:
        print(f"  ADR-0004 venter fortsatt: {len(par)} observasjoner i "
              f"{len(tabell)} bøtter.")
        print("  Trenger minst 30 observasjoner fordelt på minst 3 bøtter.")
    else:
        print("  ADR-0004 bør IKKE åpnes: ECE er for høy til at et bånd")
        print("  basert på konfidens ville vært forsvarlig.")
    print("=" * 66)
    return 0


def label_studio_svarer() -> bool:
    """Er Label Studio i det hele tatt oppe?

    «Ingen data ennå» og «kilden svarer ikke» er to helt ulike svar, og
    å blande dem ville sendt noen ut på en ukes venting på data som
    aldri kunne komme (R128: tomt er ikke det samme som ukjent)."""
    import urllib.request
    url = os.environ.get("LABEL_STUDIO_URL", "http://localhost:8080").rstrip("/")
    try:
        urllib.request.urlopen(url + "/api/projects", timeout=8)
        return True
    except urllib.error.HTTPError:
        return True          # svarte (401/403 er fortsatt et svar)
    except Exception:                                           # noqa: BLE001
        return False


def main() -> int:
    if not os.environ.get("LABEL_STUDIO_API_KEY", "").strip():
        print("LABEL_STUDIO_API_KEY er ikke satt — uten den finnes ingen "
              "fasit å måle mot.\nSett den i .env (se oppstart/LES_MEG.md).")
        return 1
    if not label_studio_svarer():
        url = os.environ.get("LABEL_STUDIO_URL", "http://localhost:8080")
        print(f"\nLabel Studio svarer ikke på {url}.")
        print("Da vet vi ingenting om kalibreringen — verken at det finnes "
              "data\neller at det ikke gjør det.")
        print("\nStart den: oppstart\\start_label_studio.bat")
        return 1
    try:
        par, hoppet = hent_par()
    except Exception as exc:                                    # noqa: BLE001
        print(f"Kunne ikke hente fra Label Studio: {exc}")
        return 1
    return skriv_rapport(par, hoppet)


if __name__ == "__main__":
    sys.exit(main())
