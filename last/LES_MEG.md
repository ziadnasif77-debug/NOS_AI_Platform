# Lasttest (§21, §26)

```
last\kjor_last.bat              100 brukere, 3 minutter
last\kjor_last.bat 20 60s       20 brukere, 1 minutt
```

Serveren må kjøre først (`oppstart\start_api.bat` eller kontrollpanelet).

## Hvorfor Locust ligger i `last\pakker` og ikke i runtimen

§21 navngir verktøyet: «Load tests skal bruke k6 eller Locust». Locust
er Python og kan derfor bo i nav (§1); k6 er en Go-binær som ikke kan.

Men Locust drar med seg **17 pakker**, blant dem `gevent` og `pyzmq` med
**kompilerte utvidelser**. `.pyruntime` er mappa som skal kunne kopieres
til en hvilken som helst server og virke — og hver kompilerte binær som
er bygget for akkurat denne Python-versjonen og dette OS-et, er en
sjanse til at det løftet brekker.

Derfor: `pip install --target last\pakker`, og `PYTHONPATH` settes bare
når lasttesten kjører. Produksjonsruntimen er urørt, og
`test_portabilitet.py` er fortsatt grønn.

Trengs mappa ikke, kan den slettes. Ingenting i tjenesten leser den.

## Hva testen dømmer på

§26 stiller **to** krav, og de kan gå hver sin vei. Riggen dømmer dem
hver for seg — én samlet dom ville skjult nettopp det som ble funnet
første gang.

### Krav 1 — «100 samtidige brukere skal ikke gi prosessomfattende kollaps»

Tidsavbrudd og kollaps ser like ut i klientens statistikk: begge blir
«HTTP 0». Forskjellen er om tjenesten lever etterpå, så riggen spør
`/hjelp` når lasten er over. Svarer den, ga klientene opp å vente — det
er noe helt annet enn en prosess som døde.

### Krav 2 — «interaktive beholder reservert kapasitet under batch-burst»

Måles som p95 på de interaktive kallene, mot en grense satt i
`GRENSE_INTERAKTIV_P95_MS` (15 s). Grensen er en **beslutning**, ikke en
måling: et menneske foran skjermen tåler noen sekunder, ikke et halvt
minutt.

## Et kontrollert avslag er en BESTÅTT test

Sier serveren «503, prøv igjen om 30 sekunder» til bruker nummer 40, har
den gjort nøyaktig det den skal. En lasttest som teller det som feil,
måler om maskinen er stor — ikke om tjenesten er robust.

Feil er: tilkoblingsbrudd, tidsavbrudd, 500, `ok: false` uten `feil`, og
503 **uten** `Retry-After` (et avslag som ikke sier når man kan prøve
igjen, er ikke kontrollert).

`202` fra `POST /jobb` er riktig svar, ikke en feil — store jobber SKAL
være asynkrone (§26). Riggen kalte det først en feil, og da ville en
test av «er store jobber asynkrone?» strøket fordi de er det.

## Tallene er maskinspesifikke — robustheten er ikke

Gjennomstrømning måles på maskinen som kjører testen. §20.1 sier det
samme om 5,2 sider/s: en planleggingsverdi til den målte
workload-baselinen foreligger.

Robustheten er derimot overførbar. Minnelekkasjer, kappløp, køer uten
tak og uhåndterte unntak oppfører seg likt på enhver maskin — og det er
dem §26 krav 1 handler om.

## Målt 2026-08-17 (ankermaskinen: 12 kjerner, RTX 3070 8 GB)

100 brukere, 2 minutter, 333 forespørsler:

| | median | p95 |
|---|---|---|
| `interaktiv: hjelp` | 120 ms | 730 ms |
| `interaktiv: spørsmål` | 17 000 ms | 91 000 ms |
| `interaktiv: felter` | 31 000 ms | 91 000 ms |
| `batch: skannet bunke` | 140 ms | 530 ms |
| `batch: 500 sider` | 210 ms | 720 ms |

**Krav 1: BESTÅTT.** Tjenesten svarte HTTP 200 rett etter stormen.
49 kontrollerte avslag (503 med `Retry-After`).

**Krav 2: STRØK.** Interaktiv p95 er 91 s mot batchens 720 ms.

Legg merke til at det er **omvendt** av hva navnene antyder: batch er
rask, interaktiv er treg. Grunnen er at `POST /jobb` bare KØER arbeidet
og svarer 202 med en gang — det tunge skjer i arbeidstråden etterpå, og
den spiser den kapasiteten de interaktive står og venter på. Det finnes
ingen reservasjon; alle deler samme port.
