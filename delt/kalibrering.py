"""Betyr konfidensen noe? — kalibrering av terskelen som styrer
gjennomgang.

Serveren sender et dokument til menneskelig gjennomgang når
OCR-konfidensen er under 0.85. Det forutsetter STILLTIENDE at tallet
betyr noe: at «0.9» faktisk er riktigere enn «0.7». Er modellen
overmodig, slipper dårlige dokumenter gjennom UTEN å bli sett — og
treningsløkken lærer da bare av feilene systemet visste om, aldri av
dem det gjorde med selvtillit.

Kalibrering måler nettopp det: del resultatene i bøtter etter oppgitt
konfidens, og sammenlign med den FAKTISKE riktigheten i hver bøtte.

    bøtte      oppgitt   faktisk   avvik
    0.9–1.0      0.95      0.71    −0.24   ← overmodig
    0.8–0.9      0.85      0.83    −0.02
    0.7–0.8      0.75      0.79    +0.04

Ett tall for hele bildet er forventet kalibreringsfeil:

    ECE = Σ (bøttestørrelse / totalt) × |oppgitt − faktisk|

    ECE < 0.05   god
    ECE > 0.15   terskelen er et vilkårlig tall

HULLET SOM MÅ LUKKES FØR TABELLEN KAN FYLLES
Dokumenter OVER terskelen sendes aldri til gjennomgang. Da finnes det
ingen fasit for dem, og de øverste bøttene — de som avgjør om terskelen
er riktig — kan ALDRI fylles. Målingen ville bekreftet seg selv: vi
måler bare der vi allerede visste at det var dårlig.

Derfor `skal_kalibreringsproeve()`: en liten, tilfeldig ANDEL av de
godt leste dokumentene sendes også til gjennomgang, merket som prøve og
ikke som «lest dårlig». Uten den er kalibrering ikke vanskelig — den er
umulig.
"""
import hashlib

# Standardbøttene. Grovere enn ti fordi et menneskelig gjennomgått
# datasett er lite: ti bøtter på tre hundre dokumenter gir tretti i
# hver, og da måler man støy igjen (R148).
BOTTER = ((0.0, 0.5), (0.5, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01))


def _botte(konfidens: float):
    for lav, hoy in BOTTER:
        if lav <= konfidens < hoy:
            return (lav, hoy)
    return BOTTER[-1]


def kalibreringstabell(par) -> list:
    """`par` = [(oppgitt_konfidens, var_riktig), …] → én rad per bøtte.

    Hver rad: {botte, antall, oppgitt, faktisk, avvik}. Bøtter uten
    observasjoner utelates — en tom bøtte er ikke «0 % riktig», den er
    fravær av data, og å tegne den som en null ville vært den samme
    løgnen som presisjon 0.0 på et ubesvart felt (R146)."""
    samlet = {}
    for konfidens, riktig in par:
        rad = samlet.setdefault(_botte(float(konfidens)),
                                {"sum_konfidens": 0.0, "riktige": 0,
                                 "antall": 0})
        rad["sum_konfidens"] += float(konfidens)
        rad["riktige"] += 1 if riktig else 0
        rad["antall"] += 1

    ut = []
    for (lav, hoy) in BOTTER:
        rad = samlet.get((lav, hoy))
        if not rad:
            continue
        oppgitt = rad["sum_konfidens"] / rad["antall"]
        faktisk = rad["riktige"] / rad["antall"]
        ut.append({
            "botte": f"{lav:.1f}–{min(hoy, 1.0):.1f}",
            "antall": rad["antall"],
            "oppgitt": round(oppgitt, 4),
            "faktisk": round(faktisk, 4),
            # NEGATIVT = overmodig: systemet lovet mer enn det holdt.
            # Det er den farlige retningen, for da slipper dårlige
            # dokumenter gjennom uten å bli sett.
            "avvik": round(faktisk - oppgitt, 4),
        })
    return ut


def ece(par) -> float:
    """Forventet kalibreringsfeil — ett tall for hele tabellen.

    Vektet etter bøttestørrelse, så en bøtte med tre dokumenter ikke
    veier like mye som en med tre hundre."""
    tabell = kalibreringstabell(par)
    totalt = sum(r["antall"] for r in tabell)
    if not totalt:
        return 0.0
    return round(sum(r["antall"] / totalt * abs(r["avvik"])
                     for r in tabell), 4)


def overmodig(par, grense: float = 0.05) -> list:
    """Bøttene der systemet lover MER enn det holder, med margin.

    Bare denne retningen: en modell som undervurderer seg selv sender
    for mange dokumenter til gjennomgang — det koster tid. En som
    overvurderer seg selv slipper feil gjennom til et vedtak."""
    return [r for r in kalibreringstabell(par) if r["avvik"] < -grense]


def skal_kalibreringsproeve(fil_id: str, andel: float) -> bool:
    """Skal dette GODT LESTE dokumentet likevel til gjennomgang?

    Avgjøres av en hash av dokumentets id, ikke av en tilfeldighet per
    kall: samme dokument skal gi samme svar hver gang. Ellers ville to
    opplastinger av samme fil kunne gi ulikt utfall, og et
    kalibreringssett bygget av slike prøver ville vært skjevt uten at
    noen kunne se hvordan.

    `andel` 0.0 = av (standarden). Da fylles aldri de øverste bøttene i
    tabellen, og kalibrering er umulig — det er et bevisst valg, ikke
    en glipp, og `kalibreringstabell` viser tomrommet ved å utelate
    bøtta i stedet for å tegne den som null."""
    if andel <= 0 or not fil_id:
        return False
    if andel >= 1:
        return True
    kutt = int(andel * 10_000)
    tall = int(hashlib.sha256(
        ("kalibrering:" + str(fil_id)).encode()).hexdigest()[:8], 16)
    return (tall % 10_000) < kutt
