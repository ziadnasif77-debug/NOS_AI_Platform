# oppstart\ — alle oppstartsfiler samlet

Alle starterne bruker prosjektets EGEN Python (`..\.pyruntime`) og setter nav-lokalt
miljø selv (`PYTHONNOUSERSITE=1` → ingen C-binding).

> **`start_kontrollpanel.bat` er hovedinngangen.** Alt du trenger startes
> derfra — inkludert **vakthunden**, som holder API-et oppe og skriver
> exitkoden når det dør. Du skal ikke måtte kjøre noe ved siden av.

| Fil | Hva den gjør | Adresse |
|-----|--------------|---------|
| **start_kontrollpanel.bat** | **HOVEDINNGANGEN.** GUI med kontrollpanelet: start/stopp av hver tjeneste (grønn/rød/gul), Start alt/Stopp alt, live-grafer for GPU/VRAM/CPU/RAM + dokumentklienten. Starter API-et **med vakthund** | — |
| **start_alt.bat** | Starter ALT **skjult i bakgrunnen** (ingen vinduer å lukke ved uhell). Bruker også vakthunden. Utskrift → `..\data\logger\oppstart_*.log` | — |
| **sjekk_status.bat** | Viser om tjenestene kjører (200 = oppe) | — |
| **stopp_alt.bat** | Stopper alle tjenestene (8600/4200/8080 + tunnel) **og vakthunden** | — |
| start_api_med_vakthund.bat | API-et under overvåking: startes på nytt hvis det dør, og exitkoden logges. Dette er det kontrollpanelet kjører | http://127.0.0.1:8600/hjelp |
| start_api.bat | Kun dokument-API-et, **uten** vakthund — synlig vindu, for feilsøking | http://127.0.0.1:8600/hjelp |
| start_prefect.bat | Kun Prefect-UI, synlig vindu. Bygger venv på nytt hvis nav ble flyttet | http://127.0.0.1:4200 |
| start_label_studio.bat | Kun Label Studio, synlig vindu. Data i `..\data\label-studio` | http://127.0.0.1:8080 |
| start_tunnel.bat | cloudflared-tunnel → offentlig lenke til API-et | https://….trycloudflare.com |
| _skjult.vbs | (intern) hjelper som kjører en .bat uten vindu, med logging | — |

## Vanlig bruk

1. **Dobbeltklikk `start_kontrollpanel.bat`** og trykk «Start alt». Det er
   hele oppskriften — API-et starter under vakthund, og du ser status,
   logger og ressursbruk i samme vindu.
2. `start_alt.bat` gjør det samme uten GUI, hvis du vil ha det på en
   snarvei eller i en planlagt oppgave.
3. **Stopp alt:** knappen i panelet, eller `stopp_alt.bat`.

Vil du SE loggen til én tjeneste live (feilsøking): kjør dens `start_*.bat` alene —
da får den et synlig vindu. De skjulte loggene ligger i `..\data\logger\oppstart_*.log`.

## Hva trenger du å starte?

- **Til daglig:** `start_kontrollpanel.bat`. Ingenting annet.
- **Produksjonsserver (kun dokumentbehandling):**
  `start_api_med_vakthund.bat` holder. Label Studio/Prefect er valgfrie
  (API-et virker uten). Bruk IKKE `start_api.bat` der — den kjører
  uovervåket, og da er det ingenting som fanger hvorfor serveren døde.
- **Ekstern tilgang:** start API-et først, deretter `start_tunnel.bat`.
  Merk at en «quick tunnel» får ny adresse hver gang den startes.

## Merknader

- **Prefect og C:** Prefect 3.7 ignorerer `PREFECT_HOME` for tre stier
  (local storage / memo store / logging) og prøver da C:\Users\… — starterne pinner
  dem eksplisitt til `..\.prefect`, så ALT ligger i nav. (Advarselen «Unable to
  write to memo_store.toml at C:\…» betydde at Prefect prøvde og FEILET — ingenting
  ble lagret på C.)
- **Label Studio** lagrer database/media i `..\data\label-studio` (følger en
  mappe-kopi). Første start ber deg opprette en bruker i nettleseren. VALGFRI.
- **API-nøkkel:** API-et kjører åpent uten `X-API-Key` med mindre du setter
  `API_NOKKEL` som maskin-miljøvariabel (`setx /M API_NOKKEL "..."`) FØR start —
  viktig hvis du eksponerer via tunnelen.
- Roten `..\START_ALT.bat` finnes fortsatt (lett variant: API + Prefect i synlige
  vinduer). Denne mappa er den fullstendige samlingen.
