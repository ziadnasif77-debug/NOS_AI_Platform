"""Én kanonisk livssyklus for en jobb — og ETT sted den defineres.

Implementeringsspesifikasjonen §6.1 krever én state machine som API,
eventer, adaptere, logger og metrikker deler. Situasjonen før dette var
verre enn ulike navn: det fantes ingen adapter i det hele tatt. Den
interne strengen gikk rett ut til klienten, så

  * OpenAPI erklærte `enum: ["ko", "arbeider", "ferdig", …]`
  * svaret inneholdt faktisk `"kø"` og `"pågår"`

Kontrakten løy altså om sine egne verdier, OG de inneholdt æøå — som
§26 uttrykkelig forbyr i maskinlesbare enum-verdier, fordi en klient
som forgrener på dem må håndtere tegnsett for å lese en statuskode.

REGELEN SOM FØLGER: ingen andre steder får produsere en statusstreng.
Arbeidstråden setter en INTERN tilstand; svarbyggeren kaller
`offentlig()`. En vakttest håndhever at ingen enum-liste skrives for
hånd noe sted — ellers oppstår nøyaktig avviket over på nytt, og det er
usynlig til en klient forgrener feil.

Spesifikasjonen tillater interne navn som avviker, så lenge de mappes
EKSPLISITT før de forlater plattformen (§6.1). Derfor beholdes de
interne navnene arbeidstråden alt bruker — kartet er kontrakten, ikke
navnene.
"""

# ── Den offentlige livssyklusen (§6.1) ──────────────────────────────
# Rekkefølgen er livsløpet; de fire siste er terminale.
I_KO = "i_ko"
SENDER = "sender"
KJORER = "kjorer"
SAMMENSTILLER = "sammenstiller"
FERDIG = "ferdig"
DELVIS = "delvis"
FEIL = "feil"
AVBRUTT = "avbrutt"

OFFENTLIGE = (I_KO, SENDER, KJORER, SAMMENSTILLER,
              FERDIG, DELVIS, FEIL, AVBRUTT)
TERMINALE = (FERDIG, DELVIS, FEIL, AVBRUTT)

# ── Interne tilstander → offentlige ─────────────────────────────────
# Venstresiden er det arbeidstråden faktisk skriver (og det som ligger
# lagret på disk fra før — derfor står de gamle navnene her selv om de
# har æøå). Høyresiden er det klienten ser.
KART = {
    "kø": I_KO,
    "ko": I_KO,
    "i_ko": I_KO,
    "sender": SENDER,
    "pågår": KJORER,
    "paagaar": KJORER,
    "arbeider": KJORER,
    "kjorer": KJORER,
    "sammenstiller": SAMMENSTILLER,
    "ferdig": FERDIG,
    "delvis": DELVIS,
    "feil": FEIL,
    "avbrutt": AVBRUTT,
    "avbrytes": KJORER,      # ba om stopp, men jobben kjører ennå
}

# Lovlige overganger, internt. En jobb som hopper fra kø rett til
# ferdig har ikke lest noe — og en tilstandsmaskin som tillater det,
# beskriver ikke systemet, den pynter på det.
LOVLIGE = {
    I_KO: (SENDER, KJORER, AVBRUTT, FEIL),
    SENDER: (KJORER, AVBRUTT, FEIL),
    KJORER: (SAMMENSTILLER, FERDIG, DELVIS, AVBRUTT, FEIL),
    SAMMENSTILLER: (FERDIG, DELVIS, FEIL, AVBRUTT),
}


def offentlig(intern: str) -> str:
    """Den offentlige tilstanden for en intern. Ukjent intern verdi gir
    `feil` — ikke sin egen streng: en tilstand ingen har definert skal
    ikke kunne lekke ut i kontrakten som om den var gyldig."""
    return KART.get((intern or "").strip().lower(), FEIL)


def er_terminal(intern: str) -> bool:
    return offentlig(intern) in TERMINALE


def kan_gaa_til(fra_intern: str, til_intern: str) -> bool:
    """Er overgangen lovlig? Terminale tilstander er endelige."""
    fra, til = offentlig(fra_intern), offentlig(til_intern)
    if fra == til:
        return True
    if fra in TERMINALE:
        return False
    return til in LOVLIGE.get(fra, ())


def openapi_enum() -> list:
    """Enum-lista til OpenAPI — HENTET, ikke skrevet av.

    Skrevet for hånd sto det «ko» og «arbeider» i spesifikasjonen mens
    svaret inneholdt «kø» og «pågår». En kontrakt som beskriver noe
    annet enn den leverer, er verre enn ingen kontrakt: klienten
    forgrener på verdier som aldri kommer."""
    return list(OFFENTLIGE)
