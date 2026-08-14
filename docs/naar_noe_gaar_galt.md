# Når noe går galt

Feilboka. Den er skrevet for deg som står med serveren og **ikke har
internett, ikke har en utvikler tilgjengelig, og ikke kjenner koden**.

Slå opp symptomet du ser. Hvert punkt sier: hva du ser → hva det betyr
→ hva du gjør. Kommandoene kjøres fra prosjektmappa (`nav\`), og de
virker uten internett.

> **Den ene regelen:** Ikke gjett. Alt viktig står i en logg, og hver
> logg står nevnt her. Finner du ikke symptomet i denne fila, ta med
> `data\logger\vakthund.log` og de siste 50 linjene av
> `data\logger\oppstart_api.log` til den som skal hjelpe deg — de to
> svarer på nesten alt.

---

## 0. Er noe i det hele tatt galt?

```
oppstart\sjekk_status.bat
```

Sier hvilke tjenester som svarer. Vil du ha en full gjennomgang av
installasjonen (Python, GPU, modeller, regler):

```
.pyruntime\python.exe skript\sjekk_miljo.py
```

Den avslutter grønt (kode 0) når alt er på plass, og skriver `[FEIL]`
foran hvert punkt som ikke er det.

---

## 1. Roboten/klienten får 502, eller ingenting svarer

**Hva du ser:** UiPath eller nettleseren får «502 Bad Gateway» fra
tunneladressen, eller `Kunne ikke koble til`.

**Hva det betyr:** 502 fra tunnelen betyr nesten alltid at **porten er
død** — altså at API-et ikke kjører. Tunnelen lever videre og har
ingenting å sende til. Tunnelen er sjelden problemet.

**Hva du gjør:**

1. Sjekk om API-et svarer lokalt:
   ```
   .pyruntime\python.exe -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8600/hjelp', timeout=10).status)"
   ```
   * Får du `200` → API-et lever, og problemet er tunnelen. Start den
     på nytt: `oppstart\start_tunnel.bat`.
   * Får du en feil → API-et er nede. Gå videre.

2. **Les hvorfor det døde** (dette er hele poenget med vakthunden):
   ```
   .pyruntime\python.exe -c "print(open(r'data\logger\vakthund.log', encoding='utf-8', errors='replace').read()[-3000:])"
   ```
   Slå opp exitkoden i punkt 2 under.

3. Start på nytt, med vakthund som holder det oppe:
   ```
   oppstart\start_api_med_vakthund.bat
   ```
   Vakthunden starter ikke en server til hvis en allerede svarer — den
   legger seg til å overvåke. Det er trygt å kjøre den.

---

## 2. Serveren dør av seg selv (exitkoder)

**Hva du ser:** I `data\logger\vakthund.log` står det
`PROSESSEN DØDE — exitkode …`.

| Exitkode | Hva det betyr | Hva du gjør |
|---|---|---|
| **3221225477** (`0xC0000005`) | **Minnetilgangsfeil — GPU-minnet tok slutt.** Native krasj i llama.cpp/CUDA. Det finnes **ingen Python-traceback** å lete etter; tolken rakk aldri å reagere. | Se punkt 3 — dette er nesten alltid VRAM. |
| **4294967295** (`0xFFFFFFFF`) | **Drept utenfra.** Ikke et krasj. Noen eller noe stoppet prosessen (Oppgavebehandling, et opprydningsskript, en omstart av maskinen). | Let etter et skript eller en operatør. Serveren har ikke gjort noe galt. |
| **1** | Vanlig Python-feil. | Da **står** feilen i loggen: se `data\logger\oppstart_api.log`. |
| **0** | Ryddig avslutning — noen stoppet tjenesten med vilje. | Start den igjen hvis den skal kjøre. |
| **3221225725** (`0xC00000FD`) | Stakkoverflyt. | Sjeldent. Ta med loggen til utvikler. |

---

## 3. GPU-minnet tar slutt (0xC0000005, eller OCR ble plutselig treg)

Dette er den vanligste alvorlige feilen, og den har **én årsak**:
språkmodellen og OCR-en deler det samme kortet på 8 GB. Tar
språkmodellen for mye, har OCR ingen plass igjen.

**To utslag, ulike symptomer:**

* **Serveren krasjer stille** (`0xC0000005`) → språkmodellen sprengte
  kortet.
* **Alt virker, men OCR ble mye tregere** → OCR falt ned på CPU fordi
  det ikke var nok ledig GPU. Det er *ment* å skje (det er tryggere enn
  et krasj), men det er et varsel om at kortet er for fullt.

**Tre verdier styrer dette. Ikke endre dem uten å lese her:**

| Verdi | Trygg verdi | Hva som skjer hvis du bommer |
|---|---|---|
| `BOREALIS_KONTEKST` | **settes av maskinen** (4096 på et 8 GB-kort) | En for høy verdi gir **segfault** under oppstart — verifisert ved 8192 på 8 GB. Serveren dør uten melding. |
| `OCR_MINSTE_LEDIG_GPU_MB` | **2600** | 800 ga stille nativ krasj. Dette er den farligste enkeltverdien i `.env`. |
| Antall GPU-lag (`BOREALIS_GPU_LAG`) | som satt | Flere lag = raskere modell, mindre plass til OCR. Senk den for å dele en større modell med RAM. |

**Serveren regner disse ut av kortet den står på** (R190). Vil du se hva
den kom fram til, og hvorfor:

```
.pyruntime\python.exe -m delt.maskinprofil
```

Den skriver kortet, minnet, hvert tak den valgte, og **den største
modellfila dette kortet tåler**. Står det en `MERK:` der, er det noe du
bør lese før du endrer noe. Setter du en verdi i `.env`, vinner din
verdi over profilen — profilen setter bare standarden.

**Hva du gjør hvis serveren krasjer med 0xC0000005:**

1. Kontroller at `.env` ikke har fått nye verdier:
   ```
   .pyruntime\python.exe -c "print(open('.env', encoding='utf-8').read())"
   ```
   Se spesielt etter `BOREALIS_KONTEKST` og `OCR_MINSTE_LEDIG_GPU_MB`.
   Står de på noe annet enn 4096 og 2600, sett dem tilbake.
2. Byttet noen modellen nylig? Rull tilbake — se punkt 5.
3. Kjører noe annet på GPU-en (et spill, en annen tjeneste, en andre
   kopi av serveren)? Steng det. To servere på samme kort er nok til å
   felle begge.

---

## 4. Svarene er blitt dårligere

**Hva du ser:** Saksbehandlere melder at uttrekk eller svar er blitt
feil, uten at noen har endret noe åpenbart.

**Hva du gjør — mål det, ikke gjett:**

1. **Kjør regresjonskorpuset** (dokumenter med fasit skrevet av et
   menneske). Serveren må kjøre først.
   ```
   .pyruntime\python.exe skript\kjor_korpus.py
   ```
   Det gir et tall. Er tallet lavere enn før, har noe faktisk blitt
   dårligere — og da vet du det, i stedet for å tro det.

2. **Kjør spørsmålskorpuset** (spørsmål med fasitsvar, måler
   språkmodellen):
   ```
   .pyruntime\python.exe skript\kjor_sporsmaalskorpus.py
   ```

3. **Har noen byttet modellvekter?** Serveren roper om det ved oppstart,
   men meldingen kan ha rullet forbi:
   ```
   .pyruntime\python.exe -m delt.motoravtrykk
   ```
   Sier den at noe er ENDRET, er tersklene i systemet kalibrert mot de
   *gamle* vektene. Rull tilbake (punkt 5), eller godta de nye bevisst
   med `--godta` etter at du har kjørt korpuset og sett at det holder.

4. **Har noen endret reglene?** Alt som styrer svarene ligger i
   `regler\`. En linje i `egne_regler.txt` påvirker hvert eneste svar.
   ```
   git status regler\
   git diff regler\
   ```

---

## 5. Bytte modell — og angre

**Bytt aldri modell uten å måle.** Verktøyet gjør det for deg, og
nekter byttet hvis kandidaten er dårligere eller ikke får plass:

```
.pyruntime\python.exe skript\bytt_modell.py <sti-til-ny-modell.gguf>
```

Det samme finnes i kontrollpanelet under fanen **Modeller**, med
knapper — du trenger ikke kommandolinja.

**Angre et bytte:**

```
.pyruntime\python.exe skript\bytt_modell.py --rull-tilbake
```

Den forrige modellen ligger i `modeller\borealis-forrige` og **slettes
aldri automatisk**. Du kan angre om en måned.

> Etter et bytte eller en rulling må serveren startes på nytt for at den
> nye modellen skal tas i bruk — modellene lastes ved oppstart.

**Håndskriftmodellen (norhand)** har sitt eget verktøy, med samme idé:

```
.pyruntime\python.exe skript\valider_modell.py --rull-tilbake
```

---

## 6. Label Studio / trening

**Label Studio starter ikke, eller du har glemt passordet:**

```
oppstart\nullstill_ls_passord.bat
```

**Ingenting kommer til gjennomgang:** Auto-gjennomgang er **av** med
mindre både `LABEL_STUDIO_URL` og `LABEL_STUDIO_API_KEY` står i `.env`.
Det er med vilje: uten dem lagrer serveren ingenting.

**Alt kommer til gjennomgang (for mye):** Da leser OCR-en dårlig. Sjekk
punkt 3 (falt OCR til CPU?) og skannerkvaliteten (`/forhandssjekk`
dømmer et dokument før prosessering).

---

## 7. Disken fylles opp

Det eneste som vokser, er gjennomgangsbildene i `data\gjennomgang`.

```
.pyruntime\python.exe skript\rydd_gjennomgang.py           # viser hva som VILLE blitt slettet
.pyruntime\python.exe skript\rydd_gjennomgang.py --slett   # sletter
```

Grensen er `OPPBEVARING_DAGER` i `.env` (standard 30).

---

## 8. Hvor loggene ligger

| Fil | Hva den svarer på |
|---|---|
| `data\logger\vakthund.log` | **Hvorfor døde serveren?** (exitkoden) |
| `data\logger\oppstart_api.log` | Python-feil ved oppstart, traceback |
| `data\logger\tilgang.log` | Hvem kalte hva, når — og OCR-konfidens per dokument |
| `data\logger\` for øvrig | Treningsløp og ryddejobber |

**Ingen av loggene inneholder dokumentinnhold eller personnumre.** De
kan derfor sendes videre for feilsøking uten personvernvurdering.

---

## 9. Nødbrems: still alt tilbake

Hvis du har endret ting og ikke husker hva:

```
git status
git diff
```

Vil du forkaste alle endringer og gå tilbake til sist fungerende
tilstand (**dette sletter endringene dine**):

```
git checkout -- .
```

`.env`, modellene og `data\` røres ikke av dette — de er ikke i git.
