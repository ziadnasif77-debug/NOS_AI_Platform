# CLAUDE.md — grunnregler for NAV dokument-AI

Dette prosjektet skal kunne KOPIERES som én mappe (`nav/`) til en hvilken
som helst server og kjøre uten videre installasjon. Reglene under er
ufravikelige og gjelder ALL kode, alle skript og all konfigurasjon.

## 1. Alt bor i nav-mappa — ingen eksterne avhengigheter

**Enhver endring og ethvert nytt tillegg skal ligge INNENFOR `nav/`.**
Ingenting prosjektet trenger for å kjøre får ligge på C:, i en
brukerprofil, i en global Python, eller noe annet sted utenfor mappa.

Før du legger til noe (pakke, modell, cache, data, verktøy), sjekk at
det havner under `nav/`:

- **Python-pakker** installeres til `nav/.python` eller
  `nav/.pyruntime/Lib/site-packages` — ALDRI til brukerens site-packages.
  `.pyruntime/Lib/site-packages/sitecustomize.py` fjerner user-site fra
  `sys.path` automatisk; ikke omgå den.
- **Modeller** ligger i `nav/modeller` (eller `nav/.cache` for
  HF-nedlastinger, `nav/.EasyOCR` for EasyOCR-vekter). Cache-stiene
  settes til nav i sitecustomize.py — ikke skriv til `~/.cache`.
- **Data, logger, jobber** under `nav/data`.
- **Stier i kode og .bat:** bruk alltid RELATIVE stier eller stier
  avledet fra prosjektroten (`%CD%` i .bat, `os.path.dirname(__file__)`
  i Python). ALDRI en hardkodet `C:\...`, brukerprofil eller absolutt
  sti utenfor nav. (Unntak: rene, frittstående testskript som allerede
  faller tilbake når en systemressurs mangler — f.eks. Windows-fonter.)

**Verifisering:** `tester/test_portabilitet.py` vokter dette. Kjør den
etter endringer som rører pakker, stier eller cache. Den feiler hvis en
avhengighet lekker ut av nav.

Mål: `python -m pytest tester/test_portabilitet.py` skal være grønn, og
serveren skal kunne startes uten en eneste miljøvariabel og fortsatt kun
laste fra `nav/`.

## 2. Norsk er obligatorisk i all kode

**All kode skrives på norsk:** funksjons- og variabelnavn, kommentarer,
docstrings, loggmeldinger, feiltekster, API-felter, prompter, commit-
meldinger og dokumentasjon. Æøå brukes normalt.

- Et hvilket som helst ord på et annet språk (spesielt arabisk) som
  sniker seg inn i kode, kommentar eller tekst, ERSTATTES UMIDDELBART
  med norsk.
- Nye endepunkter, felter og meldinger navngis på norsk fra første
  linje — ikke oversett i etterkant.
- Unntak: etablerte engelske faguttrykk som er standard i økosystemet
  (HTTP, JSON, OCR, GPU, tokens, RFC-navn) beholdes.

## 3. Test og verifiser før du sier deg ferdig

- Kjør `python -m pytest tester/ -q` og bekreft grønt før commit.
- Verifiser endringer mot den KJØRENDE serveren når det er mulig, ikke
  bare i teorien.
- Rapporter ærlig: feiler noe, si det med utdata; hopper du over et
  steg, si det.

## 4. All prompttekst bor i regler/prompter.md

**Ingen prompttekst skal skrives i Python-kode.** Alt som sendes til
språkmodellen står i `regler/prompter.md`, i navngitte blokker, og
hentes med `prompter.hent("navn", felt=...)` fra `delt/prompter.py`.

- Ny prompt eller ny regel til modellen → ny/endret blokk i
  `regler/prompter.md`, og øk `versjon` nederst i samme fil.
- Nytt kallsted → før det opp i `KALLSTEDER` i
  `tester/test_prompter_samlet.py`, ellers fanger ikke vakten det.
- Brukerens egne regler ligger i `regler/egne_regler.txt` og
  `regler/egne_etiketter.txt` — også de i `regler/`, aldri i roten.
- Endrer du ordlyden rundt «Dokument:», «Spørsmål:», «JSON-mal:» eller
  «OCR-tekst:», må `_PROMPT_ANKRE` i `dokument_api.py` oppdateres —
  ellers klippes lange dokumenter på feil sted, stille.

Skillet som gjelder: **prompten styrer, koden garanterer.** Skal noe
være garantert riktig (tall, identifikatorer, eksklusjoner), håndheves
det av kode og dokumenteres som KODE i `docs/regler_lokal_api.md`. En
prompt er sterk styring, ikke en garanti.

**Verifisering:** `tester/test_prompter_samlet.py` feiler hvis
prompttekst dukker opp i `skript/` eller `delt/`, hvis en blokk mangler,
eller hvis en plassholder står ufylt.

## 5. Portabilitetsvakten (sitecustomize.py)

`.pyruntime` er gitignorert (kopieres med mappa, ikke via git), så
selve vaktfila ligger også i `portabilitet/sitecustomize.py` (sporet).
Bygges runtimen på nytt, kjør `python portabilitet/installer_portabilitetsvakt.py`
for å legge vakten på plass igjen.
