# -*- coding: utf-8 -*-
"""Roterer en API-nøkkel i .env — UTEN at verdien vises noe sted.

    python skript/roter_nokkel.py              # roterer API_NOKKEL
    python skript/roter_nokkel.py uipath       # roterer én navngitt nøkkel
    python skript/roter_nokkel.py --vis-navn   # hvilke nøkler finnes?
    python skript/roter_nokkel.py --ny uipath  # LAG en ny navngitt nøkkel

HVORFOR VERDIEN ALDRI SKRIVES UT
En nøkkel som har vært synlig ÉN gang er brent — i en terminal som
scroller, i et skjermbilde, i en chatlogg, i en samtale med en
assistent. Det er nettopp derfor du roterer. Skriver rotasjonen ut den
NYE verdien, har den brent den i samme øyeblikk som den lagde den, og
du står der du startet.

Skriptet skriver derfor bare et FINGERAVTRYKK: de første seks tegnene
av en SHA-256 av nøkkelen. Nok til å bekrefte at den faktisk ble byttet
og at serveren bruker den samme — verdiløst for en angriper.

Trenger du selve verdien (for å legge den inn i UiPath e.l.), les den
fra .env med et verktøy du stoler på. Den ligger der, i klartekst, på
en maskin bare du har tilgang til — det er hele sikkerhetsmodellen, og
den er dokumentert slik i README.

HVA SKRIPTET GJØR
  1. leser .env
  2. lager en ny nøkkel med `secrets.token_urlsafe` (kryptografisk
     tilfeldig — ikke `random`, som er forutsigbar)
  3. skriver .env ATOMISK (tmp + os.replace): dør maskinen midt i,
     står den gamle fila urørt. En halvskrevet .env låser deg ute.
  4. tar en tidsstemplet sikkerhetskopi av den gamle, med
     brukerrettigheter bare for deg
  5. skriver fingeravtrykket til den nye

ETTERPÅ MÅ SERVEREN STARTES PÅ NYTT — .env leses ved oppstart.
"""
import hashlib
import io
import os
import re
import secrets
import shutil
import stat
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_STI = os.path.join(ROT, ".env")
# Lengde i BYTES før base64 — 32 gir 43 tegn og 256 bits entropi.
NOKKEL_BYTES = 32


def fingeravtrykk(verdi: str) -> str:
    """Seks tegn av SHA-256. Nok til å se at noe ble byttet, for lite
    til å gjette noe fra."""
    return hashlib.sha256(verdi.encode("utf-8")).hexdigest()[:6]


def les_env(sti: str) -> list:
    if not os.path.exists(sti):
        return []
    return io.open(sti, encoding="utf-8", errors="replace").read().splitlines()


def _verdi_paa_linja(linje: str):
    """(navn, verdi) hvis linja setter en variabel, ellers None.

    Samme toleranse som serverens egen .env-leser: `export` foran, og
    en `#`-kommentar bak verdien hører ikke med i den."""
    m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", linje)
    if not m:
        return None
    verdi = m.group(2).strip()
    if " #" in verdi:
        verdi = verdi.split(" #", 1)[0].strip()
    return m.group(1), verdi.strip('"').strip("'")


def nokkelnavn(linjer: list) -> dict:
    """Alle nøkler .env definerer → fingeravtrykk.

    `API_NOKLER` er en liste `navn:verdi,navn:verdi` — hver oppføring
    er en egen nøkkel og roteres hver for seg."""
    ut = {}
    for linje in linjer:
        par = _verdi_paa_linja(linje)
        if not par:
            continue
        navn, verdi = par
        if navn == "API_NOKKEL" and verdi:
            ut["API_NOKKEL"] = fingeravtrykk(verdi)
        elif navn == "API_NOKLER" and verdi:
            for bit in verdi.split(","):
                if ":" in bit:
                    k, v = bit.split(":", 1)
                    if v.strip():
                        ut[k.strip()] = fingeravtrykk(v.strip())
    return ut


def _bytt_i_nokler(verdi: str, mal: str, ny: str) -> str:
    """Bytter ÉN navngitt nøkkel inne i `API_NOKLER`, lar resten stå."""
    biter = []
    for bit in verdi.split(","):
        if ":" in bit:
            k, v = bit.split(":", 1)
            if k.strip() == mal:
                biter.append(f"{k.strip()}:{ny}")
                continue
        biter.append(bit.strip())
    return ",".join(biter)


def _skriv_env_atomisk(linjer) -> str:
    """Sikkerhetskopi + atomisk skriving. Returnerer kopiens navn.

    Kopien FOERST, og med rettigheter bare for eieren — ellers har vi
    nettopp lagt den gamle noekkelen i en verdensleselig fil. Skrivingen
    er atomisk (tmp + os.replace): doer maskinen midt i, staar den gamle
    fila uroert. En halvskrevet .env laaser deg ute av din egen server."""
    kopi = f"{ENV_STI}.{time.strftime('%Y%m%d-%H%M%S')}.bak"
    shutil.copy2(ENV_STI, kopi)
    try:
        os.chmod(kopi, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    midl = ENV_STI + ".ny"
    with io.open(midl, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(linjer) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(midl, ENV_STI)
    try:
        os.chmod(ENV_STI, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return os.path.basename(kopi)



def roter(mal: str) -> dict:
    linjer = les_env(ENV_STI)
    if not linjer:
        return {"ok": False, "feil": f"fant ingen .env i {ROT}"}
    kjente = nokkelnavn(linjer)
    if mal not in kjente:
        return {"ok": False,
                "feil": f"«{mal}» finnes ikke i .env",
                "kjente": sorted(kjente)}

    ny_verdi = secrets.token_urlsafe(NOKKEL_BYTES)
    ut, truffet = [], False
    for linje in linjer:
        par = _verdi_paa_linja(linje)
        if par and par[0] == "API_NOKKEL" and mal == "API_NOKKEL":
            ut.append(f"API_NOKKEL={ny_verdi}")
            truffet = True
        elif par and par[0] == "API_NOKLER" and mal != "API_NOKKEL":
            ut.append(f"API_NOKLER={_bytt_i_nokler(par[1], mal, ny_verdi)}")
            truffet = True
        else:
            ut.append(linje)
    if not truffet:
        return {"ok": False, "feil": f"fant ikke linja som setter «{mal}»"}

    kopi = _skriv_env_atomisk(ut)

    return {"ok": True, "navn": mal,
            "gammelt_avtrykk": kjente[mal],
            "nytt_avtrykk": fingeravtrykk(ny_verdi),
            "sikkerhetskopi": kopi}


def opprett(navn: str) -> dict:
    """Lager en NY navngitt nøkkel i API_NOKLER — verdien vises ikke.

    Roteringen kunne bare bytte en nøkkel som ALT fantes, og feilet med
    «finnes ikke i .env». Men det første man trenger når en ny maskin
    skal kobles til, er nettopp en nøkkel som ikke finnes ennå — og da
    sto man igjen med å redigere .env for hånd og finne på en verdi
    selv. En håndskrevet nøkkel er kortere og mindre tilfeldig enn
    `secrets.token_urlsafe`, og den er synlig mens den skrives.

    Navnet er klientens ID i tilgangsloggen, så det skal si hvem det er:
    «uipath-fakturamottak», ikke «nokkel2»."""
    if not navn or navn == "API_NOKKEL" or ":" in navn or "," in navn:
        return {"ok": False,
                "feil": ("navnet må være et klientnavn uten kolon eller "
                         "komma, og kan ikke være API_NOKKEL")}
    linjer = les_env(ENV_STI)
    if not linjer:
        return {"ok": False, "feil": f"fant ingen .env i {ROT}"}
    kjente = nokkelnavn(linjer)
    if navn in kjente:
        return {"ok": False,
                "feil": f"«{navn}» finnes alt — roter den i stedet",
                "kjente": sorted(kjente)}

    ny_verdi = secrets.token_urlsafe(NOKKEL_BYTES)
    ut, truffet = [], False
    for linje in linjer:
        par = _verdi_paa_linja(linje)
        if par and par[0] == "API_NOKLER":
            eksisterende = par[1].strip()
            samlet = (f"{eksisterende},{navn}:{ny_verdi}" if eksisterende
                      else f"{navn}:{ny_verdi}")
            ut.append(f"API_NOKLER={samlet}")
            truffet = True
        else:
            ut.append(linje)
    if not truffet:
        ut.append(f"API_NOKLER={navn}:{ny_verdi}")

    kopi = _skriv_env_atomisk(ut)
    return {"ok": True, "navn": navn,
            "nytt_avtrykk": fingeravtrykk(ny_verdi),
            "sikkerhetskopi": kopi}


def main() -> int:
    args = [a for a in sys.argv[1:]
            if a not in ("--vis-navn", "--ny")]
    if "--vis-navn" in sys.argv[1:]:
        kjente = nokkelnavn(les_env(ENV_STI))
        if not kjente:
            print("Fant ingen nøkler i .env")
            return 1
        print("Nøkler i .env (avtrykk, ikke verdi):")
        for navn, avtrykk in sorted(kjente.items()):
            print(f"  {navn:22} {avtrykk}")
        return 0

    if "--ny" in sys.argv[1:]:
        navn = next((a for a in args if a != "--ny"), None)
        if not navn:
            print("FEIL: --ny krever et klientnavn, f.eks. --ny uipath",
                  file=sys.stderr)
            return 1
        svar = opprett(navn)
        if not svar["ok"]:
            print(f"FEIL: {svar['feil']}", file=sys.stderr)
            if svar.get("kjente"):
                print(f"  kjente nøkler: {', '.join(svar['kjente'])}",
                      file=sys.stderr)
            return 1
        print(f"«{svar['navn']}» opprettet.")
        print(f"  avtrykk: {svar['nytt_avtrykk']}")
        print()
        print("VERDIEN VISES IKKE — en nøkkel som har vært synlig én gang,")
        print("er brent. Den står i .env. Neste steg:")
        print("  1. start serveren på nytt (.env leses ved oppstart)")
        print("  2. les verdien fra .env og legg den i klienten")
        print(f"  3. bekreft i tilgangsloggen at klient_id blir «{navn}»")
        return 0

    mal = args[0] if args else "API_NOKKEL"
    svar = roter(mal)
    if not svar["ok"]:
        print(f"FEIL: {svar['feil']}", file=sys.stderr)
        if svar.get("kjente"):
            print(f"  kjente nøkler: {', '.join(svar['kjente'])}",
                  file=sys.stderr)
        return 1

    print(f"«{svar['navn']}» rotert.")
    print(f"  avtrykk før : {svar['gammelt_avtrykk']}")
    print(f"  avtrykk nå  : {svar['nytt_avtrykk']}")
    print(f"  kopi av den gamle: {svar['sikkerhetskopi']}")
    print()
    print("VERDIEN VISES IKKE — det er hele poenget med å rotere.")
    print("Den står i .env. Neste steg:")
    print("  1. start serveren på nytt (.env leses ved oppstart)")
    print("  2. oppdater klientene som bruker nøkkelen (UiPath o.l.)")
    print("  3. slett sikkerhetskopien når du har bekreftet at alt virker")
    return 0


if __name__ == "__main__":
    sys.exit(main())
