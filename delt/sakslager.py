"""
Saksmappa som overlever forespørselen (R245).

`delt/sak.py` grupperer dokumenter en klient sender i ETT kall. Det er
nok når hele mappa kommer på én gang, men et arkiv bygges sjelden slik:
dokumentene kommer etter hvert, ofte over dager, og hver opplasting
visste ingenting om de forrige. En sak som må sendes komplett hver gang
er ikke en sak, det er en spørring.

Her ligger lagringen: en saksmappe med `sak_id` som klienten kan legge
til i, og lese tilbake.

HVA SOM LAGRES, OG HVA SOM IKKE GJØR DET
Bare dokumentPOSTENE — filnavn, tittel, type, datoer, saksnummer,
journalnummer, fødselsnummer. IKKE dokumentteksten. Teksten er den
tyngste persondataen systemet håndterer, den ligger allerede i
jobblageret for de som brukte POST /jobb, og saken trenger den ikke:
grupperingen, tidslinjen og motsigelsene regnes ut av postene alene.
Å lagre den her ville vært en ny kopi av de samme personopplysningene,
på et nytt sted, med sin egen frist å glemme.

GRUPPERINGEN LAGRES IKKE
Den REGNES ved hver lesing, av `sak.grupper_i_saker`. Grunnen er
determinisme: lagret gruppering ville frosset resultatet av reglene slik
de var den dagen, og en senere retting i grupperingen ville ikke nådd de
mappene som trengte den mest — de gamle. Postene er data; grupperingen
er en utregning, og utregninger lagres ikke.

EN MAPPE KAN INNEHOLDE FLERE SAKER
`sak_id` identifiserer mappa klienten bygger, ikke en bevist sak.
Legger klienten dokumenter fra to ulike saksnumre i samme mappe, svarer
`saker` med to — og det er ikke en feil, det er svaret: mappa er blandet,
og det skal synes. Se `sak.grupper_i_saker`.

OPPBEVARING
Én regel, ikke to: fristen følger `JOBB_OPPBEVARING_DAGER` med mindre
`SAK_OPPBEVARING_DAGER` settes uttrykkelig. Systemet skal ikke ha to
tall som betyr «hvor lenge beholder vi persondata».
"""
import json
import os
import time
import uuid

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAK_STI = os.path.join(ROT, "data", "saker")

OPPBEVARING_DAGER = int(os.environ.get(
    "SAK_OPPBEVARING_DAGER",
    os.environ.get("JOBB_OPPBEVARING_DAGER", "30")))

# Feltene som avgjør om to poster er SAMME dokument. Filnavnet er med:
# en robot som sender samme fil to ganger (retry, dobbeltkjøring) skal
# ikke få dokumentet talt to ganger i tidslinjen sin.
_LIKHETSFELT = ("filnavn", "tittel", "dato", "behandlingsdato",
                "saksnummer", "journalnummer", "fnr")


def ny_id() -> str:
    """12 hex-siffer, som jobb_id. Kort nok til å limes inn for hånd,
    langt nok til at ingen gjetter en annens mappe."""
    return uuid.uuid4().hex[:12]


def _sti(sak_id: str) -> str:
    return os.path.join(SAK_STI, f"{sak_id}.json")


def gyldig_id(sak_id: str) -> bool:
    """Er id-en trygg å bruke som filnavn?

    Uten denne kunne «../../noe» eller «C:\\noe» fra en klient peke ut av
    datamappa. Bare heksesiffer slipper gjennom — samme form `ny_id`
    lager, så en ekte id aldri avvises."""
    return bool(sak_id) and len(sak_id) <= 64 and all(
        c in "0123456789abcdef" for c in str(sak_id).lower())


def _naa() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _nokkel(post: dict) -> tuple:
    return tuple(str((post or {}).get(f) or "") for f in _LIKHETSFELT)


def lagre(mappe: dict) -> None:
    """Skriver mappa til disk ATOMISK — samme grunn som jobblageret:
    prosessen dør faktisk (0xC0000005 fra llama.cpp/CUDA), og en avkortet
    JSON-fil er en datafil som kan felle neste lesing."""
    os.makedirs(SAK_STI, exist_ok=True)
    endelig = _sti(mappe["sak_id"])
    midlertidig = endelig + ".ny"
    with open(midlertidig, "w", encoding="utf-8") as f:
        json.dump(mappe, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(midlertidig, endelig)      # atomisk på Windows og POSIX


def hent(sak_id: str):
    """Mappa, eller None når den ikke finnes eller ikke lar seg lese.

    En ødelagt fil skal koste ÉN mappe, ikke oppstarten eller kallet —
    samme lærdom som `_jobb_last_fra_disk` (R153)."""
    if not gyldig_id(sak_id):
        return None
    try:
        with open(_sti(sak_id), encoding="utf-8") as f:
            mappe = json.load(f)
    except (OSError, ValueError):
        return None
    return mappe if isinstance(mappe, dict) else None


def ny_mappe(eier=None) -> dict:
    return {
        "sak_id": ny_id(),
        "opprettet": _naa(),
        "endret": _naa(),
        "versjon": 0,
        "dokumenter": [],
        "_eier": eier,
    }


def legg_til(mappe: dict, poster: list) -> dict:
    """Legger dokumentpostene til i mappa og returnerer
    {lagt_til, duplikater}.

    Duplikater HOPPES OVER, men telles og meldes. En robot som prøver
    igjen etter et nettverksbrudd sender de samme filene på nytt; uten
    dette ville tidslinjen fått hvert dokument to ganger, og
    motsigelsessjekken sett «to personer» der det står én. Å droppe dem
    i stillhet ville vært like galt: klienten sendte ti og fikk syv, og
    forskjellen skal ikke måtte gjettes (R24)."""
    finnes = {_nokkel(p) for p in mappe.get("dokumenter") or []}
    lagt_til, duplikater = 0, 0
    for post in poster or []:
        if _nokkel(post) in finnes:
            duplikater += 1
            continue
        finnes.add(_nokkel(post))
        mappe.setdefault("dokumenter", []).append(post)
        lagt_til += 1
    if lagt_til:
        mappe["versjon"] = int(mappe.get("versjon") or 0) + 1
        mappe["endret"] = _naa()
    return {"lagt_til": lagt_til, "duplikater": duplikater}


def rydd(maks_alder_dager: int = None, naa: float = None) -> dict:
    """Sletter saksmapper eldre enn oppbevaringsfristen.

    Mappa bærer fødselsnummer og saksnummer fra ekte dokumenter. Uten
    rydding ville de ligget på disk for alltid — og en oppbevaringspolicy
    som ikke stemmer med virkeligheten er verre enn ingen policy.

    Returnerer {slettet, beholdt, frigjort_byte}."""
    frist = (maks_alder_dager if maks_alder_dager is not None
             else OPPBEVARING_DAGER)
    naa = naa if naa is not None else time.time()
    grense = naa - frist * 86400
    slettet, beholdt, byte = 0, 0, 0
    try:
        filer = os.listdir(SAK_STI)
    except FileNotFoundError:
        return {"slettet": 0, "beholdt": 0, "frigjort_byte": 0}
    for navn in filer:
        if not navn.endswith(".json"):
            continue
        sti = os.path.join(SAK_STI, navn)
        try:
            if os.path.getmtime(sti) >= grense:
                beholdt += 1
                continue
            byte += os.path.getsize(sti)
            os.remove(sti)
            slettet += 1
        except OSError:
            continue
    if slettet:
        print(f"  Ryddet {slettet} saksmappe(r) eldre enn {frist} dager "
              f"({byte // 1024} kB frigjort)")
    return {"slettet": slettet, "beholdt": beholdt, "frigjort_byte": byte}
