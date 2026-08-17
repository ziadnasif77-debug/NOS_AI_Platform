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
| 2026-08-16 | **Vakten manglet der ingen ser etter** (R201/R202): tre funn, ingen av dem fra kodegjennomgang — alle fra spoersmaal om noe annet. (a) `_finn_gguf()` valgte NYESTE .gguf uten aa sjekke noe, og en avbrutt nedlasting er alltid den nyeste; llama.cpp svarer paa en oedelagt modell med nativt krasj uten traceback. `bytt_modell.py` sjekket signaturen allerede, men den er den OVERVAAKEDE veien — veien vi DOKUMENTERER, «legg fila i mappa og restart», hadde ingen sjekk. Funnet fordi fila laa der: 6,5 MB, foerste fire bytene 00. (b) Lastetiden ble ikke maalt noe sted (`verbose=False` demper llama.cpp sin timing), saa «hvorfor tar modellen saa lang tid?» maatte besvares utenfra, av disktypen — 3,85 GB paa en 5900-omdreiners disk. Med `n_gpu_layers` hjelper ikke mmap; dette ER en diskmaaling, og den logges na. (c) Ressursgrafene i kontrollpanelet maalte HELE maskinen, men sto under tjenestelista og ble lest som tjenestenes forbruk: alle fire stoppet, CPU i 89 % — det ser ut som stoppknappen sviktet. Den virket; en videokonvertering og et annet prosjekts testkjoering holdt maskinen. Rammen sier na «HELE maskinen» og navngir stoerste forbruker. **Moensteret er felles: i alle tre var systemet riktig, men kunne ikke FORTELLE det** |
| 2026-08-17 | **Full §26/§30-verifisering — og tre hull gjennomgangen SELV fant** (R214/R216): tabellen i `docs/fase0_beslutningsrapport.md` §11 er gaatt gjennom mot spesifikasjonsteksten, ikke mot hukommelsen. Alle tre hullene kom fram ved aa lese kravet paa nytt og sjekke KODEN: (1) §30 sa «og observability», og livssyklusen var i API, eventer og adaptere — men ikke i metrikkene, saa `/metrics` kunne ikke svare paa «hvor mange jobber endte i feil?» (R214); (2) §26 sa at cachen aldri skal gi data fra et annet dokument — oppfylt ved konstruksjon, uten en eneste test (R216); (3) §26 sa «500/1000-siders», og bare 500 var kjoert. **Ett roedt punkt staar igjen: §26.3, reservert kapasitet for interaktive.** Det er en arkitekturendring (to atskilte baner) og hoerer hjemme i en ADR, ikke i en rask fiks |
| 2026-08-17 | **Svar om feil person holdes tilbake** (R213): spoersmaal om Marit ble besvart med Olas e-post, diagnose og arbeidsgiver — ikke hallusinasjon, men verdier fra en annen persons sider. `bevisvalg` rangerte Marits side hoeyest, men sendte Olas med. I det verste tilfellet svarte KODEN, ikke modellen — derfor en kodegaranti (§4) og ikke en prompt. Foerste forsoek la sjekken ved siste returpunkt; kjernen har elleve, og det verste tilfellet gikk ut av et tidlig. Na en innpakning rundt hele kjernen, samme moenster som `_ocr_side_intern`. Maalt: **109 → 111 av 133, null regresjoner**. Loeser ikke rotproblemet — bunken gir fortsatt ÉN flat feltmengde for to personer — men hindrer det farlige svaret |
| 2026-08-17 | **Sikkerhetsjordingen (§21)** (R212): alle aatte kontrollene var implementert; fem manglet en test. Viktigst: tilgangsloggens feltsett er na en LUKKET liste — legger noen til «filnavn» eller «sporsmal», feiler testen, for en logg overlever i sikkerhetskopier lenge etter at dokumentet er slettet. SSRF fikk en vakt selv om den ikke er relevant i dag: tjenesten tar imot filer, den henter dem ikke, og det skal ikke endres ved et uhell. Tre av mine egne assertions endte paa `or True` og kunne aldri feilet — fjernet |
| 2026-08-17 | **Offline-bunten ble checksum-verifisert** (R211, §23/§26): pakkeverktoeyene fantes og er UTVIDET, ikke erstattet — pakkingen skriver SHA256SUMS + release-manifest.json som siste steg, og installasjonen stopper ved avvik FOER den installerer. Planen sa «gjenbruk `avtrykk()`»; det var feil, for den hasher bare foerste MiB — og en avbrutt nedlasting har et korrekt foerste MiB (R202). Full sha256 er ikke duplisering her, det er et annet formaal. Tre utfall skilles: mangler / endret / ekstra, fordi de krever tre ulike handlinger |
| 2026-08-17 | **Lasttest (§21/§26): serveren overlever, men interaktive sultes** (R210): 100 brukere i 2 min. Krav 1 BESTAATT — tjenesten svarte HTTP 200 rett etter stormen, og «feilene» var klienter som ga opp. Krav 2 STROEK — interaktiv p95 **91 s** mot batchens **720 ms**. Omvendt av hva navnene antyder, og grunnen er at `POST /jobb` bare koeer arbeidet (202) mens det tunge skjer etterpaa og spiser kapasiteten. Ingen reservasjon; alle deler samme port. Locust i `last/pakker`, ikke i runtimen — 17 pakker med kompilerte utvidelser bryter loeftet i §1 |
| 2026-08-17 | **/innsyn-oekta fikk kontrollert utloep** (R209, §15.1): tre av fem krav var alt oppfylt — TTL 1800 s, eierkontroll, sidebilder som doer med oekta. To manglet: en utloept oekt saa ut som «finnes ikke» (404, likt en ukjent id), og korrelasjonen dekket bare principal, ikke dokumentet. Det foerste var vanskelig fordi to riktige krav kolliderte: §15.1 vil at eieren skal FAA VITE, R153 vil at en fremmed IKKE skal kunne bekrefte at id-en finnes — og etter sletting vet vi ikke lenger hvem som eide den. Loest med gravsteiner paa tre felt uten dokumentdata. **Verdt aa merke seg om egen planlegging: planen paastod at TTL og sesjonsdata manglet helt. Det var feil — jeg soekte paa «sesjon», og koden heter «økter».** Det riktige arbeidet ble mindre enn planlagt, og det ble funnet ved aa lese koden foer den ble skrevet om |
| 2026-08-17 | **Evidence metadata + de sju KPI-ene** (R207/R208): §26 krever korrelasjon til «evidence metadata» — det fantes, men som en norsk SETNING i `advarsler`. Na ligger objektet `bevis {valgte, utelatte, poeng, grunn}` ved siden av, paa alle tre svarveiene. Og §13.1 krever sju KPI-er mot baselinen `first-N-context`; én var maalt, seks fantes ikke. Maalt med samme sidebudsjett til baselinen: **precision 17,1 → 38,9 %, recall 63,3 → 90,6 %, evidence_recall 53,6 → 85,7 %, kontekst −23,7 %**. Bedre paa alt OG billigere. Konsistenssjekk: 94/118 modellbesvarte + 15/15 kodebesvarte = 109/133, noeyaktig korpusets baseline. Dermed er Phase 1s andre akseptansekrav (§24) ogsaa maalt |
| 2026-08-17 | **R6-porten bygget — og den fant bruddet paa fjerde forsoek** (R206): §26/§30 krever 10 identiske kjoeringer; det var aldri proevd. Porten proever fire veier, og de tre foerste var identiske i alle ti. Den fjerde — FRI TEKSTGENERERING — var det ikke: `Llama` lever hele serverens levetid og llama.cpp gjenbruker KV-cachen mellom kall, saa svaret avhang av hva som ble spurt om FOER det. Maalt paa samme dokument og samme spoersmaal: 319 / 424 / 398 tegn avhengig av forhistorie. Rettet med `llm.reset()` innenfor laasen; 3,2 → 4,5 s per kall er prisen. Alle fire veier na identiske i alle ti. **Laerdommen om porten selv: de tre foerste veiene ville gitt gronn port og falsk trygghet** — det var den vanskeligste veien som avslorte feilen, og den ble lagt til fordi et uttrekkbart svar er den svakeste proeven man kan gi en modell |
| 2026-08-17 | **500-sidersmaalingen med parallellitet: 1,70×, og bit-identisk tekst** (R205): den ekte veien gjennom serveren ga **18,5 min mot 27,7 sekvensielt**, med SAMME sha256 paa teksten (358 641 tegn, 13 450 rapidocr-regioner i begge). Gevinsten er maalt i to deler: det deterministiske taket alene 1,13×, parallelliteten 1,50× oppaa — samlet 1,70× mot R200-basis. Mer enn riggens 1,38 %, fordi basiskjoeringen degraderte over lengden mens den parallelle holdt farten flat. Arbeidere ved peak 25 → 15. Riggen meldte FOERST ulike hasher; det var riggen som tok feil (den hashet JSON-konvolutten med jobb_id i). Tredje gang paa ett doegn at maaleverktoeyet loey paa samme maate som koden det maaler |
| 2026-08-16 | **Den smale fiksen bygget, portet strøk — og en ELDRE feil kom for dagen** (R203/R204): laasene delt i tre og traadet sidelesing ga 1,38×, men 2 av 30 sider ble lest annerledes ogsaa etter at all haandskriftbruk var serialisert. Hypotesen om et kappløp ble maalt og FORKASTET. Aarsaken var et TIDSBUDSJETT i norhand-veien — og dermed et R6-brudd som fantes UTEN traader: samme dokument paa en travel server ga allerede et annet svar enn paa en rolig. Uoppdaget fordi det ikke var reproduserbart; parallelliteten gjorde det reproduserbart for foerste gang. **Rettet ved aa ta klokka ut av avgjoerelsen:** taket er na et ANTALL regioner utledet av den frosne enheten (R199). Maalt paa tre nivaaer foer det ble standard — CPU 0 av 10 sider endret seg, GPU 1 av 10 (tre identiske linjer ble til én, altsaa dobbeltlesing som forsvant), korpuset 109 av 133 noeyaktig som foer. Begge bryterne staar na PAA, og en vakttest nekter parallellitet uten taket. Gevinsten flytter likevel ingen arkitekturbeslutning: 25 arbeidere → 18, og begge er en klynge |
| 2026-08-16 | **Lokal fan-out maalt — porten til Phase 2** (R203): §24.1-kravet var aldri proevd. Seks traader gjennom `ocr_side` gir **0,97×** og bruker noeyaktig de samme 5,0 kjernene som EN traad — modullaasen serialiserer alt, og kjernetallet er beviset. Uten laasen 1,41×, men to av 30 sider ble lest ANNERLEDES; en sonde viste at kilden er UFCN/norhand-andrepasset (batch-avhengig generering), ikke RapidOCR: uten andrepasset er samme parallellitet BIT-IDENTISK. Andrepasset koster 24,7 % av tiden mot 2,3 % av regionene, saa den smale fiksen kan regnes: 1,21×, 25 arbeidere → 21 — og anbefales IKKE naa, fordi den ikke flytter en beslutning. Prosess-fan-out KOLLAPSET (~16 CPU-timer uten aa fullfoere 180 sider). **Fire runder ble kjent ugyldige foer en var gyldig:** et soek jeg selv startet, ffmpeg fra et annet prosjekt, riggens egen oppvarming som bare leste side 0 (141 % drift), og en runde som kollapset. Riggen kjoerer derfor grunnlinjen om igjen til slutt og kjenner runden ugyldig ved >15 % drift. **Laerdommen er om instrumentet:** en maalerigg lyver paa noeyaktig samme maate som koden den maaler |
| 2026-08-15 | **500-sidersmaalingen gjennomfoert** (R200): kravet i §30 om at en 500-siders skannet bunke fullfoerer med full dekning «uten stille truncation» var aldri proevd — det fantes ikke et slikt dokument. `skript/lag_stor_bunke.py` bygger det syntetisk. Resultat: **500 av 500 sider, alle 500 sidemarkoerer til stede, 31,4 min, 0,27 sider/s, null policy-avvik**. Det siste er den ekte proeven paa R199: over en halvtime varierer VRAM, og foer R199 ville motorvalget blitt tatt paa nytt per side. Farten faller ~10 % over lengden (0,30 → 0,27), saa dimensjonering skal gjoeres paa det LANGE tallet: 25 arbeidere, ikke 23 |
| 2026-08-15 | **De to siste Phase 0-hullene lukket** (R198/R199): kanonisk livssyklus og frosset OCR-policy — begge eksplisitte akseptansekriterier i §26/§30. Funnet underveis var verre enn ventet: det fantes ingen statusadapter i det hele tatt, saa OpenAPI lovet «ko»/«arbeider» mens svaret ga «kø»/«pågår» — verdier kontrakten aldri hadde naevnt, med æøå som §26 forbyr. Na er `delt/tilstander.py` eneste kilde, overganger kontrolleres (en terminal tilstand er endelig), og OCR-motoren fryses ved jobbstart og registreres i jobbmetadata saa side 1 og side 150 leses likt. Verifisert mot kjoerende server |
| 2026-08-15 | **Korpuset tredoblet — og det snudde gaarsdagens konklusjon** (R196): spoersmaalskorpuset utvidet fra 46 til 133. Resultatet falt fra 91 % til 67 %, ikke fordi noe ble daarligere, men fordi de gamle spoersmaalene var lette: nesten ALLE spoersmaal om side 9-10 feilet, ikke bare fire. Med det stoerre settet ble bevisvalg (R195) maalbart bedre — 89 → 109 riktige, 27 rettet mot 7 oedelagt — og RASKERE (1,71 → 0,78 s). Det avslorte ogsaa at porten brukte feil test: to kjoeringer av samme korpus er PARVISE data, og uavhengige konfidensintervaller kastet koblingen og sa «ikke skillbar» om p = 0,0008. Porten bruker na McNemar. Bevisvalg er slaatt PAA. Lærdom: et negativt maaleresultat kan bety at tiltaket ikke virker, ELLER at maalingen ikke kan se det |
| 2026-08-15 | **Bevisvalg bygget, malt — og lagt AV** (R195): mekanismen som skal loese bunkeforvekslingen fra Phase 0. Den fikset alle fire kjente feil (42/46 → 44/46), men to nye oppsto, og bootstrap-KI overlapper: paa 46 spoersmaal er +2 ikke skillbart fra tilfeldighet. Min egen kvalitetsport sa `ikke_skillbar`, og den gjelder ogsaa mitt eget arbeid. Diagnosen av de to nye feilene rettet forklaringen min: seleksjonen valgte RIKTIG side begge ganger — modellen fikk svaret foran seg og bommet likevel. Bevisvalg omfordeler forvekslingen, den fjerner den ikke. Kostnad malt: 0,63 → 6,57 s per svar. Konklusjon: korpuset paa 46 spoersmaal er for lite til aa avgjoere dette |
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
