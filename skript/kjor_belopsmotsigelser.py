"""
Måler beløpsregelen mot fasit (R248).

    .pyruntime\\python.exe skript\\kjor_belopsmotsigelser.py

Regelen «ulike beløp mellom dokumenter» sto lenge ukodet, og
begrunnelsen sto i `delt/motsigelser.py`: et vedtak og et
omgjøringsvedtak SKAL ha ulike beløp. En regel som bare ser to ulike
tall, roper på den friskeste saken i arkivet — en klage som førte fram.

`tester/korpus/belopsvarianter.json` er saker med en fasit: er dette en
MOTSIGELSE, eller er det legitimt? De legitime er de viktigste. De er
skrevet for å FALSIFISERE regelen — omgjøring, ny årssats, ulike
beløpsslag, beregningstabell, samme verdi skrevet ulikt, og ett
dokument uten dato. Går én av dem av, er regelen for vid, uansett hvor
mange ekte motsigelser den fanger.

Skriptet bygger sakene slik `/sak` gjør (samme uttrekk, samme
gruppering), kjører motsigelsessjekken og sammenligner med fasiten.
Exitkode 0 bare når alt stemmer.
"""
import json
import os
import sys

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                               # noqa: BLE001
    pass

from delt import motsigelser, sak as saksmodul
from delt.dokumentprofil import bygg_profil
from delt.motsigelser import BELOPSFELT
from delt.tekstuttrekk import (finn_dokumentdato, klassifiser_datoer,
                               sett_dato_roller, strukturert_uttrekk)

KORPUS = os.path.join(ROT, "tester", "korpus", "belopsvarianter.json")


def _post(dokument: dict) -> dict:
    """Ett dokument på den formen `delt.sak` grupperer på — bygget av
    den ekte profilen, ikke av en forenkling. Måler vi på noe annet enn
    det serveren ser, måler vi ikke regelen."""
    tekst = dokument["tekst"]
    # `dokumentdato` MÅ regnes og sendes med — den er ikke avledet av
    # datolista alene. Første utkast utelot den, alle datoene ble None,
    # og de seks legitime sakene «bestod» fordi regelen aldri fikk noe
    # å sammenligne. En måling som går grønt av mangel på data er verre
    # enn ingen måling: den ser ut som et bevis.
    datoer = sett_dato_roller(klassifiser_datoer(tekst))
    # `struktur` maa ogsaa med: uten den ble saksnummer, tittel og
    # type staaende tomme, dokumentene havnet i HVER SIN sak, og
    # regelen fikk aldri to dokumenter aa sammenligne. Andre gang
    # samme felle i samme skript — maalingen maa bygges av de samme
    # delene som serveren bruker, ikke av en forenkling som ligner.
    profil = bygg_profil(tekst, filnavn=dokument["filnavn"],
                         antall_sider=1, datoer_detaljert=datoer,
                         dokumentdato=finn_dokumentdato(datoer),
                         struktur=strukturert_uttrekk(tekst))
    dok = profil.get("dokument") or {}
    okonomi = profil.get("okonomi") or {}
    return {
        "filnavn": dokument["filnavn"],
        "tittel": dok.get("tittel"),
        "type": dok.get("type"),
        "dato": dok.get("dato"),
        "saksnummer": (profil.get("sak") or {}).get("saksnummer"),
        "fnr": (profil.get("part") or {}).get("fnr"),
        **{f: okonomi.get(f) for f in BELOPSFELT},
    }


def kjor() -> int:
    with open(KORPUS, encoding="utf-8") as f:
        korpus = json.load(f)
    feil = 0
    print("=" * 72)
    print("BELØPSREGELEN MOT FASIT — «legitim» må ALDRI gi funn")
    print("=" * 72)
    for sak in korpus["saker"]:
        poster = [_post(d) for d in sak["dokumenter"]]
        grupper = saksmodul.grupper_i_saker(poster)
        funn = [f for g in grupper
                for f in motsigelser.finn_motsigelser(g)["funn"]
                if f["type"] == "ulikt_belop"]
        ventet = sak["fasit"] == "motsigelse"
        ok = bool(funn) == ventet
        if not ok:
            feil += 1
        merke = "OK " if ok else "FEIL"
        print(f"\n[{merke}] {sak['navn']}  (fasit: {sak['fasit']})")
        if not ok:
            print(f"       {sak['hvorfor']}")
            print(f"       fikk {len(funn)} funn, ventet "
                  f"{'minst ett' if ventet else 'ingen'}")
            # Hva regelen faktisk saa — gjør en falsk positiv feilsøkbar
            for p in poster:
                belop = {f: p.get(f) for f in BELOPSFELT if p.get(f)}
                print(f"       {p['filnavn']}: dato={p['dato']} {belop}")
        for f in funn:
            print(f"       -> {f['forklaring']}")
    print("\n" + "=" * 72)
    print(f"{'ALT STEMMER' if not feil else f'{feil} avvik fra fasit'} — "
          f"{len(korpus['saker'])} saker prøvd")
    return feil


if __name__ == "__main__":
    raise SystemExit(0 if kjor() == 0 else 1)
