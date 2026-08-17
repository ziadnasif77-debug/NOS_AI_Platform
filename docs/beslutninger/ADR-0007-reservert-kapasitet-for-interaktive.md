# ADR-0007: Interaktive forespørsler får en egen, reservert kapasitetsandel

**Dato:** 2026-08-17
**Status:** Foreslått

---

## Decision

Kapasitetsporten deles i to baner med hvert sitt budsjett: en reservert
andel for interaktive forespørsler (`/dokument`, `/spor`) som batch-
arbeid aldri kan spise av, og resten til jobbarbeideren. Andelen utledes
av maskinprofilen på samme måte som `samtidige_per_gpu` (R190), og
måles av `last/locustfile.py` mot en eksplisitt p95-grense.

## Reason

§26 stiller kravet ordrett: «Interaktive forespørsler beholder reservert
kapasitet under batch-burst.» Lasttesten viser at de ikke gjør det
(R210, 100 brukere i 2 minutter på ankermaskinen):

| | median | p95 |
|---|---|---|
| `interaktiv: spørsmål` | 17 000 ms | **91 000 ms** |
| `interaktiv: felter` | 31 000 ms | **91 000 ms** |
| `batch: 500 sider` | 210 ms | **720 ms** |

Det er **omvendt av hva navnene antyder**, og mekanismen forklarer
hvorfor: `POST /jobb` bare KØER arbeidet og svarer 202 med en gang — det
tunge skjer i arbeidstråden etterpå. Batch ser rask ut fordi den ikke
har gjort jobben ennå, mens den samme jobben spiser den kapasiteten de
interaktive står og venter på. Det finnes ingen reservasjon; alle deler
`_kapasitet_port`.

76 forespørsler endte som tidsavbrudd. Tjenesten OVERLEVDE — §26s første
krav er grønt, verifisert med et helsekall etter lasten — men et svar
som kommer etter 91 sekunder er i praksis ikke et svar for et menneske
som venter foran skjermen.

## Alternatives Considered

1. **Gjøre ingenting, og la det stå som kjent gjeld.** Forkastet fordi
   §26 nevner det eksplisitt som akseptansekriterium, og fordi
   symptomet rammer nettopp den bruken tjenesten er laget for: en
   saksbehandler som spør om ett dokument.

2. **Heve `MAKS_SAMTIDIGE` / kapasitetstaket.** Forkastet: det gjør ikke
   maskinen større. Målt i R203/R205 er OCR-veien allerede
   parallellisert til 1,38×, og GPU-låsen serialiserer modellkallene
   uansett. Flere slipper inn — alle blir tregere. Dette er den
   klassiske «fikse kø ved å fjerne køen»-feilen.

3. **Egen prosess for jobbarbeideren.** Ville gitt ekte isolasjon, men
   koster en CUDA-kontekst til (~300 MiB målt i R190) på et kort som
   allerede er trangt (R194: det farlige båndet ved 2 900 MiB fritt), og
   krever IPC for jobbtilstand. Forkastet nå, ikke prinsipielt — det er
   den naturlige veien HVIS to baner viser seg utilstrekkelig.

4. **Rate-limit batch hardere.** Forkastet: straffer batch-klienten for
   noe som er en ressursfordeling internt hos oss, og løser ikke
   problemet når ÉN stor jobb kjører alene.

5. **To baner med hvert sitt budsjett (valgt).** Enkleste inngrep som
   faktisk endrer fordelingen: samme prosess, samme lås rundt GPU-en,
   men jobbarbeideren kan aldri ta den siste plassen.

## Trade-offs

**Vinnes:** interaktiv p95 blir forutsigbar under batch-last, og
§26-kravet blir målbart oppfylt i stedet for målbart brutt.

**Ofres:** samlet gjennomstrømning på batch går NED når interaktive
plasser står tomme. Det er en bevisst prioritering — en reservasjon som
aldri koster noe, er ingen reservasjon — men den skal ikke skjules i en
graf over sider/sekund.

Og en ekstra grense å forstå: en operatør som lurer på hvorfor batch går
saktere enn maskinen tåler, må kunne finne svaret. Andelen skal derfor
være synlig i `GET /hjelp` og i `/metrics`, ikke bare i koden.

## Decision Value

**Redusert operasjonell risiko**, ikke økt kapasitet.

Etterprøvbar påstand: med reservasjonen på skal `last/kjor_last.bat`
med 100 brukere gi **interaktiv p95 under 15 000 ms**
(`GRENSE_INTERAKTIV_P95_MS`) mens batch-jobber kjører, uten at antall
kontrollerte avslag (503 med `Retry-After`) øker med mer enn 25 % mot
dagens måling.

Grensen er en beslutning, ikke en måling: et menneske foran skjermen
tåler noen sekunder, ikke et halvt minutt. Den står ett sted, i
`last/locustfile.py`, slik at den ikke vurderes på nytt hver gang noen
leser en rapport.

## Debt Introduced

To budsjetter der det før var ett. Hver framtidig endring i
kapasitetslogikken må ta stilling til begge, og en feil i fordelingen
kan gi sultet batch i stedet for sultet interaktiv — samme feil, motsatt
retning.

Fordelingen blir også en ny innstilling som kan feiljusteres. Den skal
derfor utledes av maskinprofilen (R190) med et gulv, ikke settes fritt:
en reservasjon på null er det samme som ingen reservasjon, og skal ikke
kunne konfigureres fram ved et uhell.

## Risk

**Teknisk:** en deling som gjøres feil kan gi vranglås mellom de to
banene. Motvirkes ved at delingen skjer i ÉN port (`_kapasitet_port`)
og ikke som to uavhengige låser.

**Operasjonell:** batch-gjennomstrømningen faller, og det kan bli lest
som en regresjon av noen som ikke kjenner beslutningen. Derfor denne
ADR-en, og derfor skal andelen være synlig i `/hjelp` og `/metrics`.

**Sikkerhet/personvern:** ingen. Endringen rører fordeling av
kapasitet, ikke data, tilgang eller lagring. Vurdert eksplisitt, som
malen krever.

## Owner

**Ziad Nasif** — eier av dokument-API-et og den som svarer når
review-triggeren slår inn. Overføres skriftlig i denne fila hvis
eierskapet flyttes.

## Review Trigger

Ny vurdering når ETT av disse inntreffer, målt av
`last/locustfile.py`:

- interaktiv p95 over 15 000 ms i to påfølgende lastkjøringer
- kontrollerte avslag (503) over 40 % av interaktive forespørsler —
  reservasjonen er da for liten til å slippe noen inn
- batch-gjennomstrømning under 0,25 sider/s ved 100 brukere —
  reservasjonen er da for stor
- den målte belastningsbaselinen (§4) foreligger og viser en annen
  blanding av interaktivt og batch enn 9:1

## Review Date

2026-11-17

## Exit Strategy

Reservasjonen fjernes ved å sette andelen til 0, som gir dagens
oppførsel — én felles port. Det er med vilje den enkleste veien ut:
viser målingen at delingen koster mer enn den gir, skal den kunne
skrus av uten en utrulling.

Erstattes den i stedet av ekte prosessisolasjon (alternativ 3), er
denne ADR-en å regne som erstattet, og fordelingslogikken slettes i
samme endring — to mekanismer for samme formål er verre enn den ene som
var utilstrekkelig.

---

## Merknad om status

**Foreslått, ikke gjeldende.** Målingen som utløser den er gjort
(R210), men endringen er ikke implementert. §20.1 krever at en ADR
foreligger FØR arbeidet begynner — dette er den, og den er skrevet slik
at neste steg kan tas av noen andre enn forfatteren.
