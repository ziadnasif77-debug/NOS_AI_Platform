"""
Kontrollsummer for offline-leveransen (§23, §26).

§26 krever at «offline installasjon skal være reproduserbar og
checksum-verifisert». §23 sier at bunten skal inneholde `/checksums` og
`release-manifest.json`.

Pakkeverktøyene fantes fra før (`skript/pakk_for_offline.py` og
`skript/installer_offline.py`), og §23 sier at de skal GJENBRUKES og
utvides — ikke erstattes. Det som manglet var integriteten: `MANIFEST.txt`
listet hva som ble pakket, men ingenting kunne si om det kom FRAM helt.

HVORFOR IKKE `avtrykk()` FRA bytt_modell.py
Det ville vært naturlig å gjenbruke den — men den hasher STØRRELSE +
FØRSTE MiB, med vilje, fordi den er et raskt fingeravtrykk for
GB-store modellfiler. Til integritet er det feil verktøy: en avbrutt
nedlasting har et helt korrekt første MiB. Det var nøyaktig R202-feilen,
og en kontrollsum som ikke ville fanget den, er ingen kontrollsum.

Her leses derfor HELE fila. Det koster sekunder på en modell; det er
prisen for at svaret betyr noe.

TO FILER, TO FORMÅL
  SHA256SUMS            samme format som `sha256sum` — kan verifiseres
                        med standardverktøy hvis vårt ikke finnes
  release-manifest.json  §23s navn: hva bunten ER (versjon, tid, antall
                        filer, samlet størrelse), ikke bare hva den
                        inneholder
"""
import hashlib
import json
import os
import time

BLOKK = 1024 * 1024

# Filer som ALDRI skal telle med. En cache eller en logg som endrer seg
# etter pakking ville gjort enhver verifisering rød, og da slutter folk
# å kjøre den — som er verre enn ikke å ha den.
HOPP_OVER = {"SHA256SUMS", "release-manifest.json"}
HOPP_MAPPER = {"__pycache__", ".git", ".pytest_cache"}


def sha256_av(sti: str) -> str:
    """HELE fila. Se modulteksten for hvorfor ikke bare første MiB."""
    h = hashlib.sha256()
    with open(sti, "rb") as f:
        for blokk in iter(lambda: f.read(BLOKK), b""):
            h.update(blokk)
    return h.hexdigest()


def _filer(rot: str):
    for mappe, undermapper, filer in os.walk(rot):
        undermapper[:] = [d for d in undermapper if d not in HOPP_MAPPER]
        for navn in sorted(filer):
            if navn in HOPP_OVER:
                continue
            full = os.path.join(mappe, navn)
            yield full, os.path.relpath(full, rot).replace("\\", "/")


def lag(rot: str, versjon: str = None) -> dict:
    """Skriver SHA256SUMS og release-manifest.json i `rot`."""
    linjer, antall, bytes_ = [], 0, 0
    for full, relativ in _filer(rot):
        try:
            linjer.append(f"{sha256_av(full)}  {relativ}")
            antall += 1
            bytes_ += os.path.getsize(full)
        except OSError as exc:
            raise SystemExit(f"Kunne ikke lese {relativ}: {exc}")

    with open(os.path.join(rot, "SHA256SUMS"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write("\n".join(sorted(linjer)) + "\n")

    manifest = {
        "versjon": versjon or time.strftime("%Y.%m.%d"),
        "bygget": time.strftime("%Y-%m-%d %H:%M:%S"),
        "antall_filer": antall,
        "sum_bytes": bytes_,
        "algoritme": "sha256 over HELE filen",
        "verifiser_med": (
            "python skript/verifiser_kontrollsummer.py <mappe>  —  eller "
            "sha256sum -c SHA256SUMS"),
        "merknad": (
            "Kontrollsummen dekker hele filen, ikke et fingeravtrykk av "
            "starten. En avbrutt nedlasting har korrekt første MiB, og en "
            "sjekk som ikke fanger det er ingen sjekk (R202)."),
    }
    with open(os.path.join(rot, "release-manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest


def les_summer(rot: str) -> dict:
    sti = os.path.join(rot, "SHA256SUMS")
    if not os.path.isfile(sti):
        return {}
    ut = {}
    with open(sti, encoding="utf-8") as f:
        for linje in f:
            linje = linje.rstrip("\n")
            if "  " in linje:
                sum_, navn = linje.split("  ", 1)
                ut[navn] = sum_
    return ut


def verifiser(rot: str) -> dict:
    """→ {ok, mangler, endret, ekstra, sjekket}.

    Tre utfall holdes FRA HVERANDRE med vilje. «Mangler» er en ufullstendig
    kopiering, «endret» er en ødelagt eller byttet fil, og «ekstra» er noe
    som er kommet til etterpå. De tre krever ulik handling, og en samlet
    «feil» ville skjult hvilken."""
    fasit = les_summer(rot)
    if not fasit:
        return {"ok": False, "grunn": "SHA256SUMS mangler i mappa",
                "mangler": [], "endret": [], "ekstra": [], "sjekket": 0}
    funnet = {relativ: full for full, relativ in _filer(rot)}
    mangler = sorted(set(fasit) - set(funnet))
    ekstra = sorted(set(funnet) - set(fasit))
    endret = []
    for navn, forventet in sorted(fasit.items()):
        if navn in funnet:
            try:
                if sha256_av(funnet[navn]) != forventet:
                    endret.append(navn)
            except OSError:
                mangler.append(navn)
    return {"ok": not mangler and not endret,
            "mangler": mangler, "endret": endret, "ekstra": ekstra,
            "sjekket": len(fasit)}
