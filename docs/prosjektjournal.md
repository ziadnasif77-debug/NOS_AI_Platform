# Prosjektjournal — utforskning av KI i dokumentforståelse

Dette er journalen konseptutredningen («Utforskning av KI og intelligent
automatisering i Nav økonomi stønad», kap. 8) etterspør: løpende
dokumentasjon av vurderinger, beslutninger, teknologitester og
erfaringer — både det som lyktes og det som ikke gjorde det.

Journalen dekker det TEKNISKE utforskningssporet (spor 2 i utredningen):
lokal kjøring av åpne KI-modeller for dokumentforståelse. Møter,
organisering og dialogen med fagmiljøene dokumenteres utenfor dette
repoet; her står det som kan verifiseres mot kode, tester og målinger.

**Slik leses dette repoet som journal:**

| Kilde | Hva den dokumenterer |
|---|---|
| [regler_lokal_api.md](regler_lokal_api.md) | **Erfaringsloggen.** 180+ nummererte regler (R1 →), én per funnet og rettet feil eller etablert garanti — med måling, årsak og hva som håndheves av kode |
| `git log` | Kronologien. Hver commit navngir regelen den innfører |
| [endepunkter.md](endepunkter.md) | Kontrakten slik den faktisk er |
| [dokumentprofil_skjema.md](dokumentprofil_skjema.md) | Formbeslutningene — og de kjente svakhetene, navngitt |
| `tester/` (1500+ tester) | Garantiene, håndhevet — ikke lovet |

---

## 1. Hva som er bygget (status)

En frittstående, lokal dokumenttjeneste som leser et dokument én gang,
svarer og forkaster det — ingenting lagres. Alt kjører i én mappe, på
egen maskin, uten sky og uten internett etter første installasjon.
Det var et bevisst valg: skal teknologien vurderes for Nav, må den
kunne prøves under de samme rammene som gjelder for taushetsbelagt
informasjon.

Tre modeller samarbeider, alle åpne og lokale:

- **EasyOCR/RapidOCR** — trykt tekst (adaptivt motorvalg etter ledig GPU)
- **norhand v3** (Nasjonalbibliotekets TrOCR) — håndskrift, og den
  eneste modellen som finjusteres videre på egne korreksjoner
- **Borealis 4B** (Nasjonalbibliotekets norske språkmodell) — spørsmål,
  skjemautfylling, OCR-korrigering, klassifisering, sammendrag

Rundt modellene står det som viste seg å være mesteparten av arbeidet:
vakter i kode (tallvakt, sjekksumvalidering, formstabilitet),
sporbarhet per funn (side og posisjon), personvernbryter og sladding,
kvalitetsport for nytrente modeller med automatisk rull-tilbake, og en
treningsløkke der mennesker korrigerer det maskinen leste dårlig.

## 2. Dekningskart mot utredningens utforskningsområder (kap. 9)

Ærlig status per område — «ikke påbegynt» er et resultat, ikke en
mangel ved journalen:

| Område | Status | Belegg |
|---|---|---|
| 9.1 Dokumentforståelse | **I drift lokalt.** Metadata, håndskrift, kvalitetsdom, koordinater per funn. Klassifisering: regel + modellforslag med kodevalidering (R184), og typeruting: den avgjorte typen bestemmer forventede felter, `mangler` rapporteres deterministisk (R186). Sammendrag med tallvakt (R185). Sammenligning av to dokumenter: ikke påbegynt | `/dokument`, `/forhandssjekk`, R51–R55, R184–R186 |
| 9.2 Språkmodeller | **Én åpen modell grundig prøvd** (Borealis 4B, kvantisert, på 8 GB GPU). Systematisk sammenligning av flere åpne modeller: begrenset av GPU-minnet. Kommersielle tjenester: ikke prøvd — personvernvurdering må komme først, og reelle dokumenter kan ikke sendes ut | R-loggen; `bytt_grunnmodell.py` står klar for modellbytte |
| 9.3 Multimodale modeller (VLM) | **Ikke påbegynt.** 8 GB GPU er fullt utnyttet av språkmodell + OCR; en synsmodell krever mer maskinvare. Venter på infrastruktursporet med Teknologiavdelingen | Målt grense: R51 (adaptivt motorvalg etter ledig VRAM), R140 (kontekstverdien som felte tjenesten) |
| 9.4 Kunnskapssøk (RAG) | **Bevisst utelatt her.** Tjenestens bærende prinsipp er «ingenting lagres»; RAG krever en varig indeks. Hører hjemme i en egen pilot med andre data (rutiner/rundskriv, ikke borgerdokumenter) og egen personvernvurdering. Byggekloss som finnes: deterministisk lovtekstoppslag med flertydighetsvern (`delt/lover.py`) | README («lagrer ingenting»), R-loggen |
| 9.5 Saksbehandlingsstøtte | **Delvis.** Spørsmål med tallvakt, sammendrag (R185), profil på tvers av en bunke — og mangelkontroll per dokumenttype: «faktura uten beløp» er nå et felt en robot kan rute på (R186), med et målbart mellombånd i gjennomgangsrutingen (R187). Brevutkast: ikke påbegynt — en 4B-modell kan ikke garantere kvaliteten et utgående brev krever, og vaktene som måtte til finnes ikke ennå | `/dokument` (svar/oppsummer/klassifiser), dokumentprofilen |
| 9.6 Automatisering/RPA | **Kjernen i løsningen.** Bygget for UiPath: flat svarform, formstabilitet håndhevet av tester, `/ekko` til klientdiagnose, `/jobb` for store bunker. KI som utviklingsstøtte (PDD/testdata/logganalyse): ikke del av denne tjenesten | R63, R81/R99/R103, formstabilitetstestene |
| 9.7 Agentteknologi | **Ikke påbegynt** — i tråd med utredningen: kunnskap først, løsninger senere | — |

## 3. Lærdommer med overføringsverdi (beslutningsgrunnlag)

1. **Modellen er den minste delen av arbeidet.** Av 180+ dokumenterte
   rettelser handler de fleste ikke om modellen, men om det rundt:
   svar som var gale og så sikre ut, felter som løy i kanttilfeller,
   kontrakter som sprakk i stillhet. Enhver ny KI-pilot bør budsjettere
   deretter: vaktene, sporbarheten og ærligheten er hovedarbeidet.
2. **En språkmodell formulerer alltid et svar — også når den tar
   feil.** Garantier må derfor ligge i kode, ikke i prompten: tall i
   svar kreves ordrett fra dokumentet (tallvakt), identifikatorer
   valideres matematisk (mod11/mod10), og spørsmål koden kan besvare
   eksakt (sidetall, strekkoder, kontonummer) rutes forbi modellen.
3. **Lokal kjøring er reell og tilstrekkelig for utprøving.** Åpne
   norske modeller (Nasjonalbiblioteket) løser oppgavene på
   forbruksmaskinvare — men 8 GB GPU er en hard grense: én språkmodell
   pluss OCR fyller kortet, og større kontekst/synsmodeller krever
   serverkapasitet. Det er et konkret, målt innspill til
   infrastrukturdialogen.
4. **Mennesket i løkken, med port.** Dårlige lesinger går automatisk
   til manuell korreksjon (Label Studio); korreksjonene trener
   håndskriftmodellen; en ny modell settes bare i drift hvis den måles
   bedre enn den gamle på et fast valideringssett — ellers forkastes
   den, med rull-tilbake tilgjengelig. Ingen forbedring på tro alene.
5. **Start enkelt-prinsippet holdt.** OCR + regler løser mye uten
   modell; modellen legges bare på der den tilfører noe (håndskrift,
   frie spørsmål, sammendrag) — og alltid med en deterministisk vei ved
   siden av, så tjenesten svarer også når modellen er nede.
6. **Det som ikke ble noe, er også dokumentert.** Klassifiserings-,
   NER-, vektorsøk- og layoutmodeller (nb-bert, qwen3-embed, layoutlmv3
   m.fl.) ble prøvd og FJERNET (2026-07-21) — funksjonene forsvarte
   ikke GPU-plassen og kompleksiteten. Utredningens mål om å
   dokumentere «mindre hensiktsmessige» løsninger er altså oppfylt i
   praksis.

## 4. Milepæler (fra git-historikken)

| Når | Hva |
|---|---|
| 2026-06-19 | Første utgave: OCR + uttrekk + gjennomgang; Label Studio inn som korreksjonsverktøy |
| 2026-06-24 → 07 | Borealis 4B (norsk LLM) inn lokalt; spørsmål/skjema med tallvakt og kodevakter |
| 2026-07-16 → 24 | Ytelses- og ærlighetsrunder på ekte dokumenter (R49–R55): OCR 17 s → 1 s/side, håndskriftbudsjett, modellasting ut av brukerkall |
| 2026-07-21 | Opprydding: klassifiserings-/NER-/vektorsøk-/layoutmodellene fjernet; portabilitetsvakt (alt i én mappe) |
| 2026-07-31 → 08-08 | Kontraktsarbeid for RPA: flat svarform, formstabilitet, operasjonskontrakt, feilkontrakt; sikkerhet (nøkkel, rate-limit, sladd, personvernbryter); vakthund med exitkode-diagnose |
| 2026-08-03 → 08-11 | Systematisk revisjon R129–R183: personvernhull, kvalitetsport målt i stedet for antatt, ytelse/temakoder (SYK/UFO/DAG), utmattingsvern |
| 2026-08-12 | Journalen etablert; klassifiser- og oppsummer-operasjonene inn (R184, R185) som første nye KI-oppgaver etter utredningens kap. 9.1 |
| 2026-08-15 | **Forsøket som rettet min egen rapport** (R194): hypotesen «frigjør VRAM så OCR kommer på GPU» ble prøvd, ikke antatt. Svaret: ja, OCR kommer tilbake — men gevinsten er 1,24×, ikke 6,9× som første rapportutkast regnet med (R51-tallet gjaldt ett bilde uten håndskriftpass og uten Borealis lastet). Og et farligere funn: ved 2900 MB ledig, altså OVER terskelen på 2600, er OCR på GPU **tregere og ustabil** (38,97/5,31/4,94 s/side) enn CPU-reserven (3,42, stabil). Terskelen hindrer krasj, ikke treghet. Konklusjonen ble snudd: 8 GB-kortet kan ikke trimmes til å løse dette — 23 arbeidere blir 19, ikke 4 — og anbefalingen er nå å spesifisere kortet (≥12 GB), ikke å optimalisere maskinen vi har |
| 2026-08-15 | **Phase 0-måling gjennomført** (R193): `skript/kjor_ytelsesmaaling.py` måler hvert ledd utredningen krever, og [fase0_beslutningsrapport.md](fase0_beslutningsrapport.md) er skrevet av tallene. Hovedfunnet snudde anbefalingen: OCR bruker 96 % av tiden på et skannet dokument, men den EGENTLIGE flaskehalsen er VRAM — OCR falt til CPU (3,42 s/side) fordi Borealis fyller kortet, mens den samme OCR-en på GPU er målt til ~0,5 s/side. Det er 23 arbeidere mot 4 for samme last. Billigste tiltak er ikke en maskin til, men å frigjøre 1,5 GB på maskinen som står der. Språkmodellen er IKKE flaskehalsen (0,41 s/kall), så utredningens Phase 3 er ikke utløst |
| 2026-08-15 | **Målinger og beslutningsregister** (R191/R192): `GET /metrics` lukker det ene konkrete hullet for utredningens Phase 0 — sider/sekund, P95, tallvakt-rate, kapasitet og hva som binder den. Første måling mot kjørende server: **0,29 OCR-sider/sekund** på ekte skannede sider, praktisk talt identisk med utredningens eget anslag (3,3 s/side). Med utredningens formel og topplast 5,2 sider/s betyr det ~24 OCR-arbeidere — men baselinen den bygger på (500 sider per dokument) er en ANTAKELSE utredningen selv ber om å få målt. `docs/beslutninger/` gir seks ADR-er etter §29.1-malen for valg som allerede var tatt |
| 2026-08-15 | **Maskinen bestemmer takene** (R190): halvparten av grensene var født av ett kort på 8 GB og fulgte med mappa til enhver annen maskin — et 24 GB-kort arvet småkortets kontekst og brukte ikke en megabyte av det det fikk. `delt/maskinprofil.py` måler maskinen og utleder takene av målingen, usymmetrisk: fritt nedover, med tak oppover (et for høyt kontekstvindu gir nativt krasj uten traceback, ikke en feilmelding), og sikkerhetsreserver senkes aldri. Ankeret er en måling, ikke en formel. Målingen bruker `nvidia-smi`, ikke torch, fordi en CUDA-kontekst ville spist en firedel av hodrommet den skal måle. Verifisert mot kjørende server: 8 GB gir bit for bit dagens verdier, og profilen står i `/hjelp` |
| 2026-08-14 | **Drift uten ekspert** (R188/R189): serveren skal kunne stelles av noen som ikke kjenner koden, uten internett og uten hjelp. Modellbytte fikk en port som måler før og etter og ruller tilbake automatisk (`skript/bytt_modell.py`), fire førflight-sjekker som feiler høyt i stedet for stille (`delt/modellsjekk.py`), et spørsmålskorpus med fasit (45 spørsmål, hvorav en kontrollgruppe som avslører brutt ruting), en **Modeller-fane** i kontrollpanelet der alt gjøres med knapper, og feilboka [naar_noe_gaar_galt.md](naar_noe_gaar_galt.md) — symptom → årsak → kommando, bygget på ekte hendelser (0xC0000005, 502 fra tunnelen, segfault ved kontekst 8192) |
| 2026-08-13 | **Teknologivurdering** (utredningens kap. 8: også vurderinger dokumenteres): arkitekturen vår holdt opp mot fersk produksjonsforskning — «Operationalizing Document AI» (arXiv 2605.18818, mai 2026) og MADP (arXiv 2605.17159). Papirets hovedfunn — OCR er flaskehalsen, ikke språkmodellen, og GPU-kapasitet er den reelle grensen — hadde vi allerede målt uavhengig (R51). To anbefalinger derfra tatt inn i vår deterministiske form: typeruting etter klassifisering (R186) og tre-bånds gjennomgangsruting med målbart mellombånd (R187). Avvist med begrunnelse: LayoutLMv3 (2022-modell vi alt har fjernet; dagens alternativ er kompakte VLM-er), kø/database/søkeindeks (hører til nasjonalt spor — bryter «ingenting lagres»), og generisk VLM i stedet for norhand (ville kastet den norske finjusteringsløkken). Dokumentprofilen deklarert som kanonisk representasjon (dokumentprofil_skjema.md §2.7) |

## 5. Åpne spørsmål til neste fase

- Serverkapasitet/GPU: hva kreves for VLM og for å sammenligne flere
  åpne modeller side om side? (Tallgrunnlag finnes: dagens grense er
  målt, ikke antatt.) Vaktliste per 2026-08: PaddleOCR-VL (0,9B — får
  plass på 8 GB) og DeepSeek-OCR kvantisert (4–6 GB) er de første
  VLM-ene som teoretisk passer vår maskinvare, men de konkurrerer med
  Borealis om samme minne og er umålte på norsk håndskrift — riktig vei
  er en side-om-side-kjøring mot vårt eget korpus (`kjor_korpus.py`),
  ikke et bytte på magefølelse.
- Kommersielle tjenester: personvernvurdering og syntetisk testkorpus
  før noen reell prøving.
- RAG over rutiner/rundskriv: egen pilot, egne data, egen lagrings- og
  personvernprofil — gjenbruk vaktprinsippene herfra, ikke koden.
- Skjemanummer→ytelse-listen (`regler/skjemanummer_ytelse.txt`) er tom
  med vilje: den må fylles med VERIFISERTE blankettnummer fra Nav, ikke
  gjetninger (R183).

*Journalen føres videre per endring: nye oppføringer i kap. 4, nye
erfaringer i kap. 3, og statusendringer i kap. 2.*
