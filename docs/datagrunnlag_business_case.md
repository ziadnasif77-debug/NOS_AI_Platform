# Datagrunnlag vi mangler — bestilling til NAV Økonomi Stønad

**Formål:** Business caset for KI-basert dokumentbehandling kan ikke tallfeste
gevinst uten disse tallene. Dokumentet er laget for å kunne sendes videre
internt, slik at hvert tall får en eier og en kilde.

**Til:** de som eier dokumentstrøm, bemanning og prosess i Økonomi Stønad
**Fra:** RPA-teamet
**Dato:** 20. august 2026

> Vi har bevisst latt være å anslå disse tallene. Et anslag som senere viser
> seg feil, ødelegger troverdigheten til hele business caset — og de to
> første tallene i tabellen under er så avgjørende at et feilanslag der kan
> gi feil investeringsbeslutning helt alene.

---

## 1. De to tallene som betyr mest

Våre målinger viser at disse to alene avgjør om fremtidig drift krever én
maskin eller flere titalls — mer enn all teknisk optimalisering til sammen.

| # | Tall | Hvorfor det avgjør | Mulig kilde | Eier | Status |
|---|---|---|---|---|---|
| 1 | **Skannet andel** av dokumentmengden (mot digitalt født PDF med tekstlag) | Skannede sider koster 2,2–3,2 s/side maskinelt (høy ende målt 25.08.2026 når språkmodellen deler GPU-en — driftstilstanden på én maskin); tekstlag koster ~0,1 s/side. Ved 50 % skannet trengs ca. 15–21 maskiner i topplast, ved 10 % ca. 3–5 | Skanningsleverandør / dokumentmottak / arkivstatistikk | | Åpen |
| 2 | **Sider per dokument** — fordelingen, ikke bare snittet | Ved 20 sider per dokument i snitt holder én maskin til hele lasten | Arkiv-/journalstatistikk | | Åpen |

## 2. Volum

| # | Tall | Brukes til | Mulig kilde | Eier | Status |
|---|---|---|---|---|---|
| 3 | Antall dokumenter per år i Økonomi Stønad | Gevinstberegning, kostnad per dokument | Journal-/arkivstatistikk | | Åpen |
| 4 | Antall sider per år | Kapasitetsdimensjonering | Samme | | Åpen |
| 5 | Fordeling per dokumenttype (topp 10) | Valg av pilottype | Journalføringskoder | | Åpen |
| 6 | Sesongvariasjon / topplast | Dimensjonering av topplast | Driftsstatistikk | | Åpen |

## 3. Dagens prosess (baseline)

| # | Tall | Brukes til | Mulig kilde | Eier | Status |
|---|---|---|---|---|---|
| 7 | Tid per dokument i dag (lesing + registrering + kontroll) | Baseline for tidsbesparelse — **den viktigste for ROI** | Tidsstudie på et utvalg, eller erfaringstall fra fagmiljø | | Åpen |
| 8 | Årsverk/timer brukt på dokumenthåndtering per år | Årlig gevinst i kroner | Bemanningstall | | Åpen |
| 9 | Timekostnad (fullt belastet) | Omregning timer → kroner | Økonomi | | Åpen |
| 10 | Dagens feilrate i registrerte opplysninger | Kvalitetsgevinst | Kvalitetskontroll / avvikstall | | Åpen |
| 11 | Dagens kostnad per dokument | Sammenligningsgrunnlag | Utledes av 3, 7, 8, 9 | | Åpen |
| 12 | Andel dokumenter som i dag krever ekstra manuell oppfølging | Automatiseringspotensial | Fagmiljø | | Åpen |

## 4. Prosess og prioritering

| # | Spørsmål | Brukes til | Eier | Status |
|---|---|---|---|---|
| 13 | Hvilke dokumenttyper har størst volum **og** klarest struktur? | Valg av pilotomfang | | Åpen |
| 14 | Hvilke steg i saksflyten bruker mest tid på dokumentlesing? | Der gevinsten faktisk ligger | | Åpen |
| 15 | Hvor er UiPath allerede i bruk, og hvilke prosesser kan konsumere strukturerte felter direkte? | Integrasjonsvei | | Åpen |
| 16 | Verifiserte temakoder for ytelser og blankettnummer→ytelse | Løsningens liste er bevisst tom i påvente av verifiserte verdier — gjetninger er verre enn ingenting | | Åpen |

## 5. Krav og rammer

| # | Spørsmål | Brukes til | Eier | Status |
|---|---|---|---|---|
| 17 | Behandlingsgrunnlag og DPIA for pilot på ekte dokumenter | Må være på plass **før** første ekte dokument behandles | Personvern | Åpen |
| 18 | NAVs sikkerhetskrav til en lokal tjeneste som behandler taushetsbelagt informasjon | Sikkerhetsgodkjenning | Sikkerhet | Åpen |
| 19 | Hvor kan en lokal GPU-server plasseres i NAVs miljø? | Pilotens driftsplassering | Teknologi/infrastruktur | Åpen |
| 20 | Krav til redundans, overvåking og navngitt alarmmottaker | Forutsetning for produksjon (dagens løsning er én maskin) | Drift | Åpen |
| 21 | Krav til logging og arkivering av maskinelle uttrekk | Governance | Arkiv/jus | Åpen |
| 22 | Formell verifisering av lisensvilkår for modellene (Borealis, norhand, OCR) | Juridisk klarering | Jus/innkjøp | Åpen |

## 6. Data til validering

| # | Behov | Brukes til | Eier | Status |
|---|---|---|---|---|
| 23 | Representativt utvalg ekte dokumenter, med hjemmel og sikret behandling | Måling av OCR- og uttrekkskvalitet mot menneskelig fasit | | Åpen |
| 24 | Ressurs til å etablere menneskelig fasit på utvalget | Uten fasit finnes ingen nøyaktighetstall | | Åpen |
| 25 | Eksisterende systemintegrasjoner løsningen må forholde seg til | Senere produksjonsvurdering | | Åpen |

---

## Slik foreslår vi at listen brukes

1. Hvert tall får en navngitt eier og en frist.
2. Tallene i kapittel 1 og 3 prioriteres — de avgjør henholdsvis
   kostnadsbildet og gevinstbildet, og alt annet kan vente på dem.
3. Punkt 17–19 må være avklart før piloten kan starte, uavhengig av tallene.
4. Etter hvert som tall kommer inn, føres de inn i
   [business_case_ki_dokumentbehandling.md](business_case_ki_dokumentbehandling.md)
   kapittel 6, 7 og 9, som er bygget for å ta imot dem.
