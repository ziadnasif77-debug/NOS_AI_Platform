"""
Proveniens på SAK-nivå (R246) — hva saksvaret bygger hver påstand på.

`delt/opphav.py` svarer på spørsmålet for ETT dokument: hvor kom dette
feltet fra, med hvilken metode, med hvilken sikkerhet. Saksvaret hadde
ikke det. Det HADDE begrunnelser — `grunnlag` på grupperingen,
`dato_kilde` på hendelsene, `forklaring` på motsigelsene — men de var
frie strenger, hver i sin form. En klient som ville vite «hvor sikkert
er dette, og hvilket dokument står det i?» måtte lese norsk prosa og
gjette.

SAMME ORDFORRÅD, IKKE ET NYTT
Metodene og konfidensnivåene importeres fra `opphav`. To vokabularer
for samme spørsmål ville før eller siden blitt uenige (R111), og et
kodeverk som bare gjelder halve svaret er verre enn ingen: en klient som
forgrener på «metode» må kunne bruke samme gren begge steder.

ÉN FORSKJELL FRA DOKUMENTNIVÅET, OG DEN ER NØDVENDIG
Et dokumentopphav peker på en SIDE. Et saksopphav må peke på et
DOKUMENT — «side 4» er meningsløst når saken består av tolv filer.
Derfor bærer hver oppføring `dokumenter`, og `side` er med når
opplysningen faktisk står på en bestemt side i en bestemt fil.

BEVIS → TOLKNING → KONKLUSJON
Dette er skillet en saksbehandler trenger, og som saksvaret manglet.
Hver oppføring sier hva som er MÅLT (`metode`), hvor sterkt det er
(`konfidens`), og hva vi sluttet av det (`begrunnelse`). En gruppering
på et merket saksnummer er noe helt annet enn en tidslinjeplassering
basert på en mottaksdato — begge er nyttige, men de er ikke like sterke,
og et svar som viser dem likt inviterer til å behandle dem likt.

KARTET SIER IKKE MER ENN SVARET
Pekerne peker INN i saksvaret, med de samme indeksene. Endres svaret,
endres pekerne — de er en projeksjon av det som faktisk står der, ikke
en egen sannhet ved siden av (samme regel som `bygg_opphav`).
"""
from delt.opphav import KONFIDENSNIVAA, METODER, NIVAAER  # noqa: F401

# «viktige» er standard, som på dokumentnivå: pekerne en klient faktisk
# handler på. Her er det to slag — hva som BANDT saken sammen, og hva
# som er GALT med den. Alt annet (hver enkelt hendelse, hver relasjon)
# kommer med `opphav=alle`.
VIKTIGE_SLAG = ("nokkel", "motsigelse")


def _post(metode, konfidens, begrunnelse=None, dokumenter=None,
          side=None) -> dict:
    """Én oppføring. Feltene er alltid til stede, tomt er `null` — samme
    regel som resten av huset.

    `dokumenter` er saksnivåets svar på dokumentnivåets `side`: hvilke
    filer opplysningen er hentet fra. Tom liste ville vært en påstand om
    at ingen dokumenter bærer den; finnes ingen, står det `null`."""
    return {"metode": metode, "konfidens": konfidens,
            "begrunnelse": begrunnelse or None,
            "dokumenter": sorted(dokumenter) if dokumenter else None,
            "side": side}


def _navn(dok: dict) -> str:
    return str((dok or {}).get("filnavn")
               or (dok or {}).get("tittel") or "dokument uten navn")


def _nokkelopphav(sak: dict) -> dict:
    """Hva bandt disse dokumentene sammen — og hvor sterkt.

    Et saksnummer er tildelt av etaten og står merket i dokumentet;
    metoden er derfor «etikett», ikke «regel». Uten nøkkel er metoden
    «ingen», og det er et ærligere svar enn å utelate oppføringen: en
    manglende peker leses som «vi målte ikke», og her HAR vi målt."""
    nokkel = sak.get("nokkel")
    dokumenter = sak.get("dokumenter") or []
    if not nokkel:
        return _post("ingen", "ingen", sak.get("grunnlag"),
                     [_navn(d) for d in dokumenter])
    felt, verdi = nokkel.get("felt"), nokkel.get("verdi")
    baerer = [_navn(d) for d in dokumenter
              if "".join(str(d.get(felt) or "").split()) == verdi]
    # Bærer ALLE dokumentene nøkkelen, er bindingen direkte. Bærer bare
    # noen, henger resten med via en ANNEN delt nøkkel — fortsatt bevist,
    # men ett ledd lenger unna, og det skal svaret vise.
    alle = len(baerer) == len(dokumenter)
    return _post("etikett", "hoy" if alle else "middels",
                 sak.get("grunnlag"), baerer)


def _hendelsesopphav(hendelse: dict) -> dict:
    """Hvorfor hendelsen ligger der den ligger i tiden.

    Dokumentets egen dato er sterkere enn en behandlingsdato: den ene
    sier når dokumentet ble skrevet, den andre når noen tok imot det.
    Begge er nyttige; å vise dem likt inviterer til å lese en
    mottaksdato som en vedtaksdato."""
    kilde = hendelse.get("dato_kilde")
    dokument = [_navn(hendelse)] if hendelse.get("filnavn") else None
    sider = hendelse.get("sider") or []
    side = sider[0] if len(sider) == 1 else None
    if kilde == "dokumentdato":
        return _post("etikett", "hoy",
                     "dokumentets egen dato", dokument, side)
    if kilde == "behandlingsdato":
        return _post("etikett", "middels",
                     "dokumentet har ingen egen dato — plassert etter "
                     "behandlingsdatoen (mottatt/arkivert)",
                     dokument, side)
    return _post("ingen", "ingen",
                 "dokumentet har ingen dato og er ikke plassert i tid",
                 dokument, side)


def _motsigelsesopphav(funn: dict) -> dict:
    """Motsigelser er REGLER, ikke målinger — bortsett fra den ene som
    hviler på mod11.

    «Flere personer» er bevist av kontrollsifferet i fødselsnummeret;
    derfor «sjekksum». «Umulig rekkefølge» er en logisk regel anvendt på
    to datoer; derfor «regel». Å kalle dem det samme ville skjult at det
    ene er matematikk og det andre er en slutning."""
    slag = funn.get("type")
    metode = "sjekksum" if slag == "flere_personer" else "regel"
    return _post(metode, "hoy", funn.get("forklaring"),
                 funn.get("dokumenter"))


def _relasjonsopphav(relasjon: dict) -> dict:
    """Personsammenfall er mod11 — matematikk, ikke navnelikhet."""
    return _post("sjekksum", "hoy", relasjon.get("forklaring"))


def bygg_saksopphav(saker: list, relasjoner: list = None,
                    nivaa: str = "viktige") -> dict:
    """JSON Pointer → opphav, for påstandene i saksvaret.

    `nivaa`:
      ingen    — tomt kart (klienten vil ikke ha det)
      viktige  — hva som bandt saken, og hva som er galt med den
      alle     — også hver hendelse i tidslinjen og hver personrelasjon

    Pekerne følger saksvaret: `/saker/0/nokkel` er nøkkelen til første
    sak, `/saker/0/tidslinje/hendelser/2/dato` den tredje hendelsen der.
    Samme indekser som svaret, så en klient slår opp uten å gjette."""
    if nivaa == "ingen":
        return {}
    alle = nivaa == "alle"
    kart = {}
    for i, sak in enumerate(saker or []):
        if not isinstance(sak, dict):
            continue
        kart[f"/saker/{i}/nokkel"] = _nokkelopphav(sak)
        for j, funn in enumerate((sak.get("motsigelser") or {}).get("funn")
                                 or []):
            kart[f"/saker/{i}/motsigelser/funn/{j}"] = \
                _motsigelsesopphav(funn)
        if not alle:
            continue
        tidslinje = sak.get("tidslinje") or {}
        for j, hendelse in enumerate(tidslinje.get("hendelser") or []):
            kart[f"/saker/{i}/tidslinje/hendelser/{j}/dato"] = \
                _hendelsesopphav(hendelse)
        for j, hendelse in enumerate(tidslinje.get("uten_dato") or []):
            kart[f"/saker/{i}/tidslinje/uten_dato/{j}"] = \
                _hendelsesopphav(hendelse)
    if alle:
        for i, relasjon in enumerate(relasjoner or []):
            kart[f"/relasjoner/{i}"] = _relasjonsopphav(relasjon)
    return kart
