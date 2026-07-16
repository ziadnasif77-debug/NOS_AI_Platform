# Fase 5 — Docker, K8s, ytelse, skalerbarhet og resiliens

**Metode:** delegert infrastrukturgjennomgang + live resiliens- og
ytelsestester mot kjørende stack.

---

## Live-verifiserte tester

| Test | Resultat | Klassifisering |
|---|---|---|
| **Redis nede under opplasting** (REL-1) | Klient får HTTP 500, men jobben er trygt `QUEUED` i Postgres (commit-før-rpush). Ghost-detektor re-køer når Redis er tilbake | bekreftet ved kjøring |
| **Opplasting 1000 sider** (SLA) | 1,9 sekunder (~2 ms/side) — se F5-ytelse | bekreftet ved kjøring |
| **`docker stop` worker** (SIGTERM) | Umiddelbar død, ingen drain (se F2-2) | bekreftet ved kjøring |
| GPU-deling (vLLM + workers på 8 GB) | 4-bit + `gpu-memory-utilization=0.60` → 4,7 GB samlet, kjører | bekreftet ved kjøring |

---

## KRITISKE funn

### F5-1 · KRITISK · Ingen `.dockerignore`
**Fil:** repo-rot (mangler). Alle images bygges med `context: .`. Uten
`.dockerignore` sendes `data/` (PDF-er), `modeller/` (~17 GB), `.git/` og `.env`
(ekte hemmeligheter) inn i build-konteksten → treg bygging + risiko for
hemmeligheter i image-lag.
**Klassifisering:** bekreftet ved kjøring (fil finnes ikke).
**Fiks:** `.dockerignore` med `data/ modeller/ .git .env .venv __pycache__ *.log tester/`.

### F5-2 · KRITISK · Postgres publisert til host med trivielle credentials
**Fil:** `docker-compose.yml:276-277` (`5432:5432`) + `:273-274` (`nav`/`nav`).
Hele databasen med NAV-dokumenter nåbar fra host-nettet med gjettbare
credentials. **Fiks:** `127.0.0.1:5432:5432` (kun lokal) + passord fra secret.
**Klassifisering:** bekreftet ved kjøring — `docker port nav-postgres-1` gir
`5432/tcp -> 0.0.0.0:5432` (publisert på ALLE grensesnitt, ikke bare localhost).

### F5-3 · KRITISK · Ingen minnegrenser i compose — OOM-risiko på delt GPU
**Fil:** `docker-compose.yml` (ingen `mem_limit`/`deploy.resources.limits`).
ocr/nlp/llm deler samme 8 GB GPU uten VRAM-tak; en voksende modell kan OOM-e
naboer. **Fiks:** eksplisitt `mem_limit` per worker; kun `llm` eier GPU via
`LLM_URL`-modus. **Klassifisering:** utledet fra kode.

### F5-4 · KRITISK · K8s RWO-PVC monteres av flere pods
**Fil:** `k8s/02-pvc.yaml:9,19` (RWO) montert av api/sok/4 workers/CronJobs.
ReadWriteOnce kan ikke monteres av pods på ulike noder → deploy henger i
`ContainerCreating`; KEDA (10 replicas) forsterker. **Fiks:** ReadWriteMany
(NFS/CephFS/Azure Files) for delte volum; skill read-only modell-volum.
**Klassifisering:** utledet fra manifester.

## HØY

### F5-5 · Høy · Floating pip-versjoner i alle worker-Dockerfiler
**Fil:** alle 5 worker-Dockerfiler + backup/oppbevaring. `torch`/`transformers`/
`paddlepaddle`/`kfp` uten pin → ikke-reproduserbare bygg, uforutsigbar
image-størrelse, risiko for CPU/GPU-feilvariant av torch.
**Fiks:** `krav.txt` med pinnede versjoner (som api/sok gjør) + `torch` mot
riktig CUDA-`--index-url`. **Klassifisering:** bekreftet ved kodelesing.

### F5-6 · Høy · Ingen non-root USER i noen Dockerfile
Alle 9 images kjører som root, med host-volum montert. **Fiks:** `useradd -m app && USER app`.

### F5-7 · Høy · Manglende resource requests/limits i K8s
Kun de to CronJobs har `resources`. postgres/redis/milvus/sok/api/workers/llm
mangler → ingen kapasitetsstyring; KEDA-skalering kan utmatte noder. **Fiks:**
sett requests/limits på alle; GPU-workers trenger `limits.nvidia.com/gpu`.

### F5-8 · Høy · Manglende liveness/readiness-probes i K8s
Mangler på redis, etcd, minio, milvus, label-studio, sok, reconciliation, alle
4 workers. Hengte pods restartes aldri. **Fiks:** readiness+liveness (TCP 9101 /
HTTP /helse).

### F5-9 · Høy · Prometheus finnes ikke i K8s — foreldreløse scrape-annotasjoner
`10-api.yaml`/`13-workers.yaml` har `prometheus.io/scrape`, men ingen
Prometheus-deployment i `k8s/`. Ingen alarmregler/Alertmanager noe sted.
**Fiks:** deploy Prometheus (kubernetes_sd) + alarmer (kølengde, worker-nede,
backup-feil) + Alertmanager.

## MIDDELS/LAV

- **F5-10 · Middels** · `build-essential` beholdt i runtime-image (lag1/lag2) → store images; ingen multi-stage.
- **F5-11 · Middels** · Manglende healthchecks i compose på alle workers + infrastruktur (redis/milvus/etcd/minio).
- **F5-12 · Middels** · `reconciliation_worker` skrapes ikke + mangler `METRIKK_PORT` (observability-hull).
- **F5-13 · Middels** · Ingen PodDisruptionBudgets; api/sok/redis/milvus på 1 replica = SPOF-er.
- **F5-14 · Middels/Lav** · MinIO `minioadmin/minioadmin`, Grafana `admin/admin` (interne, derav lavere).
- **F5-15 · Middels** · `k8s/01-hemmeligheter.yaml` plaintext-secret i git (dokumentert dev-only, men i historikk).
- **F5-16 · Lav** · PVC mangler `storageClassName`; `nav-data` 10Gi + postgres 5Gi kan bli trangt.

---

## Ytelse og skalerbarhet mot 60M sider/år

**Målt:** opplasting 1000 sider = 1,9 s. Ekstrapolert til 60M sider ≈ 60 000
opplastinger à 1000 sider = håndterbart på API-siden.

**Hva knekker først (utledet):**
1. **Postgres-tilkoblinger (F2-1):** tilkobling-per-jobb uten pool. Ved høy
   worker-parallellitet nås `max_connections=100`. **Første flaskehals.**
2. **GPU-gjennomstrømning:** én 8 GB GPU. Borealis-4B (~sek/dokument) er
   taket for NLP. 60M sider/år ≈ 1,9 sider/sek jevnt — krever flere GPU-noder
   (K8s + KEDA er forberedt, men RWO-PVC (F5-4) blokkerer horisontal spredning).
3. **audit_log-vekst:** 2 rader/side × 60M = 120M+ rader, aldri slettet, med
   manglende `event_type`-indeks (F2-6) → reconciliation-scans degraderer.
4. **Milvus:** 60M vektorer × 1024 dim ≈ betydelig RAM; ikke dimensjonert her.

**SLA-samsvar:** upload enkeltside < 200 ms holder; flersidig skalerer lineært
(~2 ms/side), dokumentert i README.

## Gjort bra (verifisert)

- Commit-før-rpush bevist live (Redis-nede-test: jobb trygt QUEUED)
- Pinnede base-images (python:3.11-slim, postgres:16-alpine, redis:7-alpine)
- God lag-cache-rekkefølge (deps før kode)
- CronJobs eksemplarisk konfigurert (concurrencyPolicy, deadline, resources,
  backup→oppbevaring-rekkefølge)
- Gjennomtenkt GPU-strategi (llm eier GPU, workers HTTP-klienter, KEDA-klar)
- K8s-secrets via secretKeyRef; `.env` gitignored
- Milvus degradert modus + fallback-kjeder
