# oppstart\ — alle oppstartsfiler samlet

Alle starterne bruker prosjektets EGEN Python (`..\.pyruntime`) og setter nav-lokalt
miljø selv (`PYTHONNOUSERSITE=1` → ingen C-binding). Du kan dobbeltklikke hver enkelt,
eller kjøre `start_alt.bat` for å starte alt.

| Fil | Hva den gjør | Adresse |
|-----|--------------|---------|
| **start_alt.bat** | Starter API + Prefect + Label Studio (hver i eget vindu) | — |
| **start_api.bat** | Kun dokument-API-et (OCR + Borealis) | http://127.0.0.1:8600/hjelp |
| **start_prefect.bat** | Kun Prefect-UI (overvåker treningsflyten). Bygger venv på nytt hvis nav ble flyttet | http://127.0.0.1:4200 |
| **start_label_studio.bat** | Kun Label Studio (menneskelig korrektur). Data i `..\data\label-studio` | http://127.0.0.1:8080 |
| **start_tunnel.bat** | cloudflared-tunnel → offentlig lenke til API-et | https://….trycloudflare.com |
| **stopp_alt.bat** | Stopper alle tjenestene (8600/4200/8080 + tunnel) | — |

## Hva trenger du å starte?

- **Produksjonsserver (kun dokumentbehandling):** `start_api.bat` — evt. `start_prefect.bat`
  hvis du vil se treningsflyten. Label Studio trengs IKKE (API-et sender dårlig lesing
  dit best-effort, men virker fint uten).
- **Utviklings-/annoteringsmaskin (alt):** `start_alt.bat`.
- **Ekstern tilgang:** start API-et først, deretter `start_tunnel.bat`.

## Merknader

- **Label Studio** er en egen tjeneste (annotering for opplæring). Første start lager en
  database i `..\data\label-studio` og ber deg opprette en bruker i nettleseren. Den er
  VALGFRI for selve dokument-API-et.
- **Prefect** er valgfri (overvåking). Hoppes trygt over hvis venv-en ikke kan bygges
  uten internett.
- **API-nøkkel:** API-et kjører åpent uten `X-API-Key` med mindre du setter
  `API_NOKKEL` som maskin-miljøvariabel (`setx /M API_NOKKEL "..."`) FØR start — viktig
  hvis du eksponerer via tunnelen.
- Roten `..\START_ALT.bat` finnes fortsatt og starter API + Prefect (den «lette»
  produksjonsvarianten). Denne mappa er den fullstendige samlingen.
