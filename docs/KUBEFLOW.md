# NAV Archive på Kubernetes + Kubeflow (kubeflow-modus)

I kubeflow-modus erstattes Redis-køene av **Kubeflow Pipelines**:
hvert opplastet dokument blir én pipeline-run med synlige steg
(preprocess → ocr → nlp → routing) i KFP-UI-et. Postgres er fortsatt
eneste kilde til sannhet — tilstand, resultater og audit-logg er
uendret fra redis-modus.

```
POST /last-opp  ──►  API (K8s Deployment)
                      │  Postgres: UPLOADED → QUEUED
                      ▼
              KFP-run «dokument-<id>»
      ┌─────────────┬──────────┬──────────┬───────────┐
      │ preprocess  │   ocr    │   nlp    │  routing  │
      │ nav/lag0    │ nav/lag1 │ nav/lag2 │ nav/lag3  │
      └─────────────┴──────────┴──────────┴───────────┘
        alle steg leser/skriver Postgres via kfp_steg.py
```

Basistjenestene (Postgres, Redis, Milvus, Label Studio, søk, API)
kjører som vanlige Kubernetes-ressurser i `k8s/` — Kubeflow kan ikke
huse permanente tjenester. Alt legges i `kubeflow`-namespacet slik at
pipeline-podene når tjenestene via standard-DNS og deler PVC-er.

## Forutsetninger (lokalt, Windows)

1. Docker Desktop med **Kubernetes aktivert**
   (Settings → Kubernetes → Enable Kubernetes → Apply & Restart)
2. Minst **16 GB RAM** tildelt — KFP + Milvus + modeller er tunge
3. `kubectl` (følger med Docker Desktop)

## Oppsett steg for steg

```powershell
# 1. Installer Kubeflow Pipelines (standalone, ~5 min første gang)
make kfp-installer
kubectl get pods -n kubeflow        # vent til alle er Running

# 2. Bygg alle images lokalt (Docker Desktop deler image-lager med K8s)
make k8s-bygg

# 3. Start NAV-tjenestene
make k8s-start
make k8s-status                     # vent til alle er Running

# 4. Opprett databaseskjemaet
make k8s-init-db

# 5. Kopier nedlastede modeller inn i PVC-en (krever make last-ned-modeller først)
make k8s-kopier-modeller
```

## Bruk

```powershell
# Last opp et dokument (API på NodePort 30080)
curl -X POST http://localhost:30080/last-opp/ -H "X-API-Key: lokal-test-nokkel" -F "fil=@test.pdf"

# Følg kjøringen i KFP-UI-et
make kfp-ui                         # åpne deretter http://localhost:8888

# Sjekk status/resultat/audit via API-et
curl -H "X-API-Key: lokal-test-nokkel" http://localhost:30080/jobb/<job_id>
```

- **API**: http://localhost:30080
- **Label Studio**: http://localhost:30880
- **KFP-UI**: http://localhost:8888 (via `make kfp-ui`)

## Treningspipeline (LayoutLMv3)

Kompilert som `kubeflow/trenings_pipeline.yaml`. Last den opp i
KFP-UI-et (Pipelines → Upload) og kjør manuelt eller på tidsplan:
eksporter fra Label Studio → konverter til LayoutLMv3-format →
finjuster. Modellene skrives til nav-modeller-PVC-en.

## Kjente begrensninger i kubeflow-modus

| Tema | Redis-modus | Kubeflow-modus |
|------|-------------|----------------|
| Retry | 3 forsøk med backoff via kø | Ingen kø-retry — feil går rett til DLQ og kjøringen feiler |
| Ghost-gjenoppretting | Reconciliation re-køer til Redis | Re-kø plukkes ikke opp — re-trigg via API-et |
| GPU | `deploy.resources` i compose | Ikke satt opp lokalt — stegene kjører på CPU |
| Oppstartstid per steg | Worker er varm (modell lastet) | Hvert steg starter ny pod og laster modellen på nytt |

Sistnevnte er den reelle kostnaden ved kubeflow-modus: OCR-/NLP-steg
betaler modell-lasting per dokument. For produksjonsvolum (30–60 mill.
sider) anbefales redis-modus for dokumentflyten og Kubeflow kun for
treningspipelinen.

## Bytte tilbake til redis-modus

Sett `KJOREMODUS: redis` (eller fjern variabelen) i `k8s/10-api.yaml`
og deploy worker-Deployments i stedet — eller kjør docker-compose-oppsettet
som før. Ingen datamigrering trengs; Postgres-skjemaet er identisk.
