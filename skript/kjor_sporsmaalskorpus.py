"""
Spørsmålskorpuset: måler SPRÅKMODELLEN mot en menneskeskrevet fasit.

Regresjonskorpuset (kjor_korpus.py) måler det deterministiske
uttrekket — felter, identifikatorer, strekkoder. Det sier ingenting om
hva modellen svarer på et fritt spørsmål. Dette skriptet fyller det
hullet, og er grunnlaget modellbytte-porten (bytt_modell.py) dømmer på:
uten et tall her, er «den nye modellen føles bedre» det eneste
kriteriet som finnes.

    .pyruntime\\python.exe skript\\kjor_sporsmaalskorpus.py
    .pyruntime\\python.exe skript\\kjor_sporsmaalskorpus.py --json  # maskinlesbart

Serveren må kjøre. Modellen som måles er den serveren HAR lastet —
skriptet bytter ingenting.

TRE TALL, IKKE ETT
  riktige svar   hovedmålet
  determinisme   samme spørsmål to ganger = samme svar (R6)
  tallvakt-rate  hvor ofte modellen ble stoppet i å dikte tall (R147)

En modell med flere riktige svar OG hoppende tallvakt er ikke bedre.
Den er heldigere.
"""
import json
import os
import re
import sys
import time

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from delt import modellsjekk                                    # noqa: E402

FASIT_MAPPE = os.path.join(ROT, "tester", "korpus")
DOKUMENT_MAPPE = os.path.join(ROT, "data", "korpus")
BASE = os.environ.get("KORPUS_API", "http://127.0.0.1:8600")
# Ett spørsmål av gangen mot en 4B-modell på et delt kort: raust.
TIDSFRIST_S = int(os.environ.get("SPORSMAALSKORPUS_FRIST_S", "300"))


def _api_nokkel() -> str:
    """Nøkkelen fra miljøet, ellers fra .env — samme grep som
    kjor_korpus.py, av samme grunn (korpuset gikk en gang 401 over hele
    linja da nøkkelen ble innført)."""
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


MANGLER = object()


def hent_sti(data, sti: str):
    """Slår opp «struktur.identifikatorer.kontonummer.0» i et svar."""
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


def _normaliser(tekst: str) -> str:
    """Små bokstaver, og mellomrom inne i tall fjernet.

    «4 812,00» og «4812,00» er det SAMME beløpet skrevet på to måter, og
    en fasit som bare godtar den ene formen måler skrivemåte, ikke
    riktighet. Hardt mellomrom (NBSP) og smalt hardt mellomrom er med —
    de er usynlige i en tekstredigerer og har felt sammenligninger før
    (R156)."""
    t = (tekst or "").lower()
    for tegn in (" ", " ", " "):
        t = t.replace(tegn, " ")
    # mellomrom MELLOM sifre fjernes; mellomrom ellers beholdes
    t = re.sub(r"(?<=\d)[ ](?=\d)", "", t)
    return t


def _inneholder(svar: str, bit: str) -> bool:
    return _normaliser(bit) in _normaliser(svar)


def vurder_svar(sp: dict, svar: str, dokumentsvar: dict) -> tuple:
    """(bestatt, grunn). Fire sjekktyper, alle deterministiske.

    `felt` sammenligner mot det deterministiske uttrekket i SAMME svar,
    så fødselsnumre og kontonumre aldri må stå i fasitfila (den ligger i
    git for alltid)."""
    if not (svar or "").strip():
        return False, "tomt svar"

    for bit in sp.get("maa_inneholde") or []:
        if not _inneholder(svar, bit):
            return False, f"mangler «{bit}»"

    ett_av = sp.get("ett_av") or []
    if ett_av and not any(_inneholder(svar, b) for b in ett_av):
        return False, "ingen av de godtatte formene: " + ", ".join(
            f"«{b}»" for b in ett_av)

    for bit in sp.get("maa_ikke_inneholde") or []:
        if _inneholder(svar, bit):
            return False, f"inneholder «{bit}», som ikke skal stå der"

    for nokkel in ("felt", "ogsaa_felt"):
        sti = sp.get(nokkel)
        if not sti:
            continue
        verdi = hent_sti(dokumentsvar, sti)
        if verdi is MANGLER or verdi in (None, "", []):
            # Uttrekket fant ingenting å sammenligne med. Da kan vi ikke
            # dømme svaret — og «kan ikke dømmes» skal ikke telle som
            # bestått (samme skille som R146: mangler ≠ galt).
            reserve = sp.get("reserve_inneholder") or []
            if reserve and all(_inneholder(svar, b) for b in reserve):
                continue
            return False, f"uttrekket har ingen verdi på «{sti}» å måle mot"
        if not _inneholder(svar, str(verdi)):
            return False, f"svaret mangler verdien uttrekket fant på «{sti}»"

    return True, "ok"


def _sporsmalskall(sti: str, sporsmal: str, nokkel: str) -> dict:
    """Ett spørsmål mot /dokument. Returnerer hele svaret."""
    import requests
    with open(sti, "rb") as f:
        svar = requests.post(
            BASE + "/dokument",
            files={"fil": (os.path.basename(sti), f, "application/pdf")},
            data={"sporsmal": sporsmal, "struktur": "ja"},
            headers={"X-API-Key": nokkel}, timeout=TIDSFRIST_S)
    svar.raise_for_status()
    return svar.json()


def _svarteksten(data: dict) -> str:
    """Svarteksten uansett hvilken svarform serveren brukte."""
    for sti in ("svar.svar", "svar"):
        verdi = hent_sti(data, sti)
        if isinstance(verdi, str) and verdi.strip():
            return verdi
    for res in data.get("resultater") or []:
        if isinstance(res, dict) and res.get("type") == "svar":
            indre = (res.get("data") or {}).get("svar")
            if isinstance(indre, str):
                return indre
    return ""


def _tallvakt_stoppet(data: dict) -> bool:
    """Grep tallvakten inn i DETTE svaret? `uverifiserte_tall` er lista
    over tall som ble fjernet — `[]` betyr «vakten kjørte, stoppet
    ingenting», `null` betyr «aldri innom» (R147/R128)."""
    for sti in ("svar.uverifiserte_tall", "uverifiserte_tall"):
        verdi = hent_sti(data, sti)
        if isinstance(verdi, list):
            return bool(verdi)
    return False


def kjor(fasit: dict, gjenta_for_determinisme: int = 3) -> dict:
    """Kjører hele korpuset mot den kjørende serveren."""
    sti = os.path.join(DOKUMENT_MAPPE, fasit["fil"])
    if not os.path.isfile(sti):
        return {"ok": False,
                "feil": f"Fant ikke dokumentet: {sti}. Dokumentene ligger "
                        "ikke i git — kopier data/korpus/ fra servermappa."}
    nokkel = _api_nokkel()
    sporsmaal = fasit["sporsmaal"]
    rader, stoppet_av_tallvakt = [], 0
    t0 = time.time()

    for nr, sp in enumerate(sporsmaal, 1):
        start = time.time()
        try:
            data = _sporsmalskall(sti, sp["sporsmal"], nokkel)
        except Exception as exc:                                # noqa: BLE001
            rader.append({"id": sp["id"], "bestatt": False,
                          "grunn": f"kallet feilet: {exc}"[:160],
                          "sekunder": round(time.time() - start, 1),
                          "svares_av": sp.get("svares_av", "modell")})
            print(f"  [{nr}/{len(sporsmaal)}] {sp['id']}: FEIL — {exc}"[:150])
            continue
        svar = _svarteksten(data)
        bestatt, grunn = vurder_svar(sp, svar, data)
        if _tallvakt_stoppet(data):
            stoppet_av_tallvakt += 1
        rader.append({"id": sp["id"], "bestatt": bestatt, "grunn": grunn,
                      "sekunder": round(time.time() - start, 1),
                      "svares_av": sp.get("svares_av", "modell"),
                      "svar": svar[:300]})
        merke = "OK  " if bestatt else "FEIL"
        print(f"  [{nr}/{len(sporsmaal)}] {merke} {sp['id']}: {grunn}"[:150])

    # --- determinisme (R6): gjenta noen spørsmål og krev samme svar ---
    determinisme = {"ok": True, "avvik": []}
    modellsporsmaal = [s for s in sporsmaal
                       if s.get("svares_av", "modell") == "modell"]
    for sp in modellsporsmaal[:gjenta_for_determinisme]:
        try:
            a = _svarteksten(_sporsmalskall(sti, sp["sporsmal"], nokkel))
            b = _svarteksten(_sporsmalskall(sti, sp["sporsmal"], nokkel))
        except Exception as exc:                                # noqa: BLE001
            determinisme["avvik"].append(f"{sp['id']}: kunne ikke måles ({exc})"[:140])
            continue
        dom = modellsjekk.determinisme_dom(a, b)
        if not dom["ok"]:
            determinisme["ok"] = False
            determinisme["avvik"].append(
                f"{sp['id']}: to ulike svar på samme spørsmål")
    if determinisme["avvik"]:
        determinisme["ok"] = False

    modellrader = [r for r in rader if r["svares_av"] == "modell"]
    koderader = [r for r in rader if r["svares_av"] == "kode"]
    return {
        "ok": True,
        "dokument": fasit["fil"],
        "antall": len(rader),
        "bestatt": sum(1 for r in rader if r["bestatt"]),
        "modell_bestatt": sum(1 for r in modellrader if r["bestatt"]),
        "modell_antall": len(modellrader),
        "kode_bestatt": sum(1 for r in koderader if r["bestatt"]),
        "kode_antall": len(koderader),
        "sekunder_totalt": round(time.time() - t0, 1),
        "sekunder_per_svar": round((time.time() - t0) / max(1, len(rader)), 2),
        "tallvakt": modellsjekk.tallvakt_dom(stoppet_av_tallvakt, len(rader)),
        "determinisme": determinisme,
        # Vektoren porten trenger for å regne konfidensintervall: 1/0 per
        # spørsmål, i fast rekkefølge. Uten den kan to modeller bare
        # sammenlignes på ett punkttall — og det er nøyaktig det R148
        # slo fast at ikke holder.
        "utfall": [1 if r["bestatt"] else 0 for r in rader],
        "rader": rader,
    }


def les_fasit(navn: str = "sporsmaal_syntetisk_bunke.json") -> dict:
    with open(os.path.join(FASIT_MAPPE, navn), encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    som_json = "--json" in sys.argv
    fasit = les_fasit()
    if not som_json:
        print(f"\nSpørsmålskorpus: {len(fasit['sporsmaal'])} spørsmål mot "
              f"{fasit['fil']}")
        print(f"Server: {BASE}\n")
    resultat = kjor(fasit)
    if som_json:
        print(json.dumps(resultat, ensure_ascii=False))
        return 0 if resultat.get("ok") else 1
    if not resultat.get("ok"):
        print(f"\nAVBRUTT: {resultat.get('feil')}")
        return 1

    print("\n" + "=" * 62)
    print(f"  RIKTIGE SVAR:  {resultat['bestatt']} av {resultat['antall']}"
          f"  ({100.0 * resultat['bestatt'] / max(1, resultat['antall']):.0f} %)")
    print(f"    modellen svarte:  {resultat['modell_bestatt']} av "
          f"{resultat['modell_antall']}")
    print(f"    koden svarte:     {resultat['kode_bestatt']} av "
          f"{resultat['kode_antall']}   (kontrollgruppe — skal alltid være full)")
    print(f"  SEKUNDER PER SVAR: {resultat['sekunder_per_svar']}")
    print(f"  TALLVAKT: {resultat['tallvakt']['forklaring']}")
    det = resultat["determinisme"]
    print("  DETERMINISME: " + ("samme svar hver gang" if det["ok"]
                                else "ULIKE SVAR — " + "; ".join(det["avvik"])))
    print("=" * 62)

    feilet = [r for r in resultat["rader"] if not r["bestatt"]]
    if feilet:
        print("\nSpørsmål som ikke ble besvart riktig:")
        for r in feilet:
            merke = "[kode] " if r["svares_av"] == "kode" else ""
            print(f"  - {merke}{r['id']}: {r['grunn']}")
        if any(r["svares_av"] == "kode" for r in feilet):
            print("\n  ADVARSEL: et [kode]-spørsmål feilet. De besvares "
                  "deterministisk forbi modellen — feiler de, er RUTINGEN "
                  "brutt, ikke modellen.")
    return 0 if not feilet else 1


if __name__ == "__main__":
    sys.exit(main())
