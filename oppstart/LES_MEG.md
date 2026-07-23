# oppstart\ — alle oppstartsfiler samlet

Alle starterne bruker prosjektets EGEN Python (`..\.pyruntime`) og setter nav-lokalt
miljø selv (`PYTHONNOUSERSITE=1` → ingen C-binding).

| Fil | Hva den gjør | Adresse |
|-----|--------------|---------|
| **start_kontrollpanel.bat** | Åpner GUI-et med **kontrollpanelet**: start/stopp av hver tjeneste (grønn/rød/gul), Start alt/Stopp alt, live-grafer for GPU/VRAM/CPU/RAM + dokumentklienten | — |
| **start_alt.bat** | Starter ALT **skjult i bakgrunnen** (ingen vinduer å lukke ved uhell). Utskrift → `..\data\logger\oppstart_*.log` | — |
| **sjekk_status.bat** | Viser om tjenestene kjører (200 = oppe) | — |
| **stopp_alt.bat** | Stopper alle tjenestene (8600/4200/8080 + tunnel) | — |
| start_api.bat | Kun dokument-API-et (OCR + Borealis), synlig vindu | http://127.0.0.1:8600/hjelp |
| start_prefect.bat | Kun Prefect-UI, synlig vindu. Bygger venv på nytt hvis nav ble flyttet | http://127.0.0.1:4200 |
| start_label_studio.bat | Kun Label Studio, synlig vindu. Data i `..\data\label-studio` | http://127.0.0.1:8080 |
| start_tunnel.bat | cloudflared-tunnel → offentlig lenke til API-et | https://….trycloudflare.com |
| _skjult.vbs | (intern) hjelper som kjører en .bat uten vindu, med logging | — |

## Vanlig bruk

1. **Start alt:** dobbeltklikk `start_alt.bat` → alt kjører skjult i bakgrunnen.
2. **Er alt oppe?** `sjekk_status.bat` (API-et trenger ~30–60 sek på Borealis).
3. **Stopp alt:** `stopp_alt.bat`.

Vil du SE loggen til én tjeneste live (feilsøking): kjør dens `start_*.bat` alene —
da får den et synlig vindu. De skjulte loggene ligger i `..\data\logger\oppstart_*.log`.

## Hva trenger du å starte?

- **Produksjonsserver (kun dokumentbehandling):** `start_api.bat` holder. Label
  Studio/Prefect er valgfrie (API-et virker uten).
- **Utviklings-/annoteringsmaskin:** `start_alt.bat` (alt, skjult).
- **Ekstern tilgang:** start API-et først, deretter `start_tunnel.bat`.

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
