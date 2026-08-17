# ADR-0006: Kø, database og multi-node utsettes til Phase 0 er målt

**Dato:** 2026-08-15
**Status:** Gjeldende

---

## Decision

RabbitMQ, Redis, delt objektlagring, søkeindeks og multi-node HA bygges
ikke nå. Phase 0 (måling + beslutningsrapport) gjennomføres først.

## Reason

Konseptutredningen (v1.6) beskriver et plattformlag for 250 000
sider/dagen. Belastningstallene er merket som ANTAKELSER i utredningen
selv: «500×500 baseline: brukes midlertidig» og «Skannet andel 50 %:
skal måles — viktigste sizing-variabel».

## Alternatives Considered

1. **Bygge plattformlaget nå.** Forkastet: utredningens egen
   ikke-forhandlebare regel er «No new infrastructure without a
   measurable bottleneck». Å bryte den i første leveranse ville
   undergravd hele styringsmodellen.
2. **Bygge en delmengde (bare kø).** Forkastet: en kø uten målt behov er
   en komponent som må driftes, overvåkes og feilsøkes — uten kjent
   gevinst.
3. **Måle først (valgt).** Utredningens Phase 0.

## Trade-offs

Vinnes: vi unngår å bygge for et volum som kanskje ikke finnes. Er det
reelle gjennomsnittet 20 sider per dokument og ikke 500, faller
dimensjoneringen med en faktor 25, og Phase 2 blir aldri nødvendig.

Ofres: er tallene riktige, har vi ikke begynt på arbeidet ennå.

## Decision Value

Redusert operasjonell kostnad og redusert risiko. Én målt variabel
(andel skannede sider) avgjør om vi trenger ~23 OCR-arbeidere eller én.

## Debt Introduced

Ingen kode-gjeld. Men tiden går: blir målingen aldri gjort, står vi
stille med en begrunnelse som ser fornuftig ut.

## Risk

At «vi måler først» blir en unnskyldning for å ikke gjøre noe. Motvirket
av review-datoen under, som gjelder selv om ingen trigger slår inn.

## Owner

**Ziad Nasif** — eier av dokument-API-et, og den som svarer når
review-triggeren slår inn. Overføres skriftlig i denne fila hvis
eierskapet flyttes.

## Review Trigger

Phase 0-beslutningsrapporten er ferdig, ELLER en målt bottleneck som
lokal fan-out ikke løser (planleggingsterskel i utredningen: 5,2
OCR-sider/sekund).

## Review Date

2026-11-01

## Exit Strategy

Beslutningsrapporten avgjør. Viser den at én node holder, lukkes denne
posten med «ikke nødvendig». Viser den det motsatte, åpnes Phase 2 med
egne ADR-er per komponent.
