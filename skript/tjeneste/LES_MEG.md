# Kjør dokument-API-et som en Windows-tjeneste

Gjør at serveren **starter av seg selv ved oppstart** og **restarter
automatisk hvis den krasjer** — uten Docker, uten ekstra nedlasting.
Bruker den innebygde Oppgaveplanleggeren (Task Scheduler), så den virker
også på en isolert server uten internett.

## Installer

Åpne PowerShell **som administrator**, og kjør:

```powershell
cd skript\tjeneste
powershell -ExecutionPolicy Bypass -File installer_tjeneste.ps1
```

Da registreres oppgaven `NAV-Dokument-API` som starter serveren ved
maskinoppstart, som `SYSTEM` (ingen pålogging nødvendig).

### Hvis GPU-en ikke er synlig som SYSTEM

Noen driveroppsett lar ikke `SYSTEM`-kontoen nå skjermkortet. Ser du
CUDA-feil i `data\logger\dokument_api.feil.log`, installer i stedet
**din egen brukersesjon** (starter ved pålogging — tryggest for GPU):

```powershell
powershell -ExecutionPolicy Bypass -File installer_tjeneste.ps1 -VedInnlogging
```

## Styr tjenesten

| Handling | Kommando |
|---|---|
| Start nå | `schtasks /run   /tn "NAV-Dokument-API"` |
| Stopp    | `schtasks /end   /tn "NAV-Dokument-API"` |
| Status   | `schtasks /query /tn "NAV-Dokument-API" /v /fo LIST` |
| Avinstaller | `powershell -ExecutionPolicy Bypass -File avinstaller_tjeneste.ps1` |

Serveren svarer på `http://127.0.0.1:8600/hjelp` når den er klar.

## Konfigurasjon (API-nøkkel, port, m.m.)

Tjenesten kjører som `SYSTEM`, så den ser **maskin-miljøvariabler**, ikke
dine brukervariabler. Sett dem én gang med `setx /M` (krever admin), og
start tjenesten på nytt:

```powershell
setx /M API_NOKKEL "din-hemmelige-nokkel"
setx /M DOKUMENT_API_PORT "8600"
setx /M LABEL_STUDIO_URL "http://localhost:8080"
setx /M LABEL_STUDIO_API_KEY "..."
```

Alle variabler er valgfrie (se [.env.example](../../.env.example)).

## Logg

- `data\logger\dokument_api.ut.log` — normal utskrift
- `data\logger\dokument_api.feil.log` — feil og avslutningskoder

## Hva skjer ved krasj?

Oppgaveplanleggeren restarter serveren automatisk (opptil 999 ganger, ett
minutt mellom hvert forsøk). Stopper du den selv med `/end`, restartes den
**ikke** — det regnes som en villet stopp.

## Alternativ: NSSM (ekte Windows-tjeneste)

Vil du ha `net start/stop`, oppføring i `services.msc` og loggrotasjon,
kan du bruke **NSSM** (én liten `nssm.exe`, ~350 kB, må kopieres til
serveren):

```powershell
nssm install NAV-Dokument-API "C:\...\skript\tjeneste\kjor_dokument_api.bat"
nssm set     NAV-Dokument-API AppDirectory "C:\...\nav"
nssm start   NAV-Dokument-API
```

Task Scheduler-varianten over er standardvalget fordi den ikke krever noe
ekstra på den isolerte serveren.
