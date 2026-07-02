# Hybrid-arkitektur: Redis-produksjon + Kubeflow-trening

Produksjonssporet (dokumentflyt) og treningssporet (modell-livssyklus)
er fullstendig adskilt. Redis + permanente workers gir lav latens og
lav kostnad for daglig drift; Kubeflow brukes der det faktisk skinner —
trening, validering og utrulling av nye modellversjoner.

## Arkitekturdiagram

```
────────────────────────── PRODUKSJONSSPOR (24/7) ──────────────────────────

  Bruker ──POST /last-opp──► API (K8s Deployment, replicas ≥ 2)
                              │  idempotens (sha256) · auth (api_nokkel/oidc)
                              │  Postgres: UPLOADED → QUEUED  (commit FØR push)
                              ▼
                        Redis queue:preprocess
                              │ blpop
                              ▼
                   preprocessing-worker (Deployment ×N)
                              │ queue:ocr
                              ▼
                   ocr-worker (Deployment ×N, GPU, modell varm)
                              │ queue:nlp
                              ▼
                   nlp-worker (Deployment ×N, GPU, modell varm)
                              │ queue:routing
                              ▼
                   routing-worker (Deployment ×N)
                         ┌────┴─────┐
                     APPROVED    REVIEW/REJECTED
                         │            │
                         ▼            ▼
                   Milvus/sok    Label Studio ──┐
                                                │ korreksjoner
      Postgres = eneste kilde til sannhet       │
      (jobs · results · audit_log · DLQ)        │
                                                │
────────────────────────── TRENINGSSPOR (ved behov) ────────────────────────
                                                │
                                                ▼
              Kubeflow Pipeline (trenings_pipeline.yaml)
        eksporter ──► konverter ──► finjuster LayoutLMv3
                                        │
                                        ▼
                     Modellregister = nav-modeller-PVC
                     (versjonerte kataloger + backup før overskriving)
                                        │
                                        ▼
             kubectl rollout restart deployment/nlp-worker
             (rullerende — null nedetid, se «Modelloppdatering»)

──────────────────────────── SIKKERHETSNETT ────────────────────────────────

  ReconciliationWorker (hvert 5. min): stuck låser · ghost-jobber · tapte
  KEDA: skalerer workers på Redis-kølengde (14-autoskalering.yaml)
  Prometheus/Grafana: kø-dybde, feilrate, latens per steg
```

## Hvorfor hybrid — målt begrunnelse

| | Kubeflow per dokument | Redis + varme workers |
|---|---|---|
| Kostnad per dokument | pod-oppstart 10–30 s + modellasting 20–60 s | ~0 (modell allerede i minnet) |
| Marginal behandlingstid | 30–90 s overhead × 4 steg | 0,5–5 s totalt (CPU), raskere på GPU |
| 30–60 mill. sider/år (~2–4 sider/sek) | urealistisk: tusenvis av pods/time | 3–6 GPU-workers holder |
| RAM/CPU | last modell på nytt per dokument | last én gang, gjenbruk |
| Synlighet per dokument | KFP-UI per run | audit_log + Grafana |

Kubeflow-modusen beholdes som opsjon (`KJOREMODUS=kubeflow`) — nyttig
for feilsøking av enkeltdokumenter med visuell steg-for-steg-visning.

## Kapasitetsestimat (60 mill. sider/år)

- 60M sider/år ≈ 165 000/dag ≈ 2/sek jevnt fordelt (topper: 4–8/sek)
- OCR er flaskehalsen: ~1–3 s/side på GPU → **4–8 ocr-workers med GPU**
- NLP: ~0,5–1,5 s/side → 2–4 nlp-workers
- Preprocessing/routing: CPU-bundet, millisekunder → 2 stk hver holder
- Postgres: ~200 skriv/sek på topp — godt innenfor én instans med SSD;
  partisjoner `audit_log` per måned ved arkivering
- Redis: kølengde er den viktigste skaleringsindikatoren → KEDA

## Migrasjonsplan (fra kubeflow-only til hybrid) — ALLEREDE GJENNOMFØRT

1. ✅ Worker-Deployments lagt til (`k8s/13-workers.yaml`)
2. ✅ API satt til `KJOREMODUS=redis` (`k8s/10-api.yaml`)
3. ✅ KEDA-autoskalering på kølengde (`k8s/14-autoskalering.yaml`, valgfri)
4. ✅ Treningspipeline uendret på Kubeflow (`kubeflow/trenings_pipeline.yaml`)
5. ✅ Dokumentpipeline beholdt som feilsøkingsverktøy

Ingen datamigrering: begge moduser deler samme Postgres-skjema og
tilstandsmaskin. Bytte frem/tilbake = én miljøvariabel + rollout.

## Modelloppdatering uten nedetid

1. Treningspipelinen skriver ny modell til `nav-modeller`-PVC-en i en
   versjonert katalog og tar backup av forrige (`finjuster.py` gjør
   dette allerede: `layoutlmv3-backup-<tidsstempel>`)
2. `kubectl rollout restart deployment/nlp-worker deployment/ocr-worker`
3. K8s ruller én pod om gangen (`maxUnavailable: 25 %` standard):
   gamle pods behandler ferdig køene sine, nye starter med ny modell
4. Optimistisk låsing + reconciliation garanterer at ingen dokumenter
   mistes under overlappingen — samme garanti som ved krasj
5. Rulles tilbake med `kubectl rollout undo` + gjenopprett backup-katalog

## Strategier (implementert)

| Strategi | Løsning |
|----------|---------|
| **Kø** | Redis lists (rpush/blpop) — enkelt, raskt, rebuildes fra Postgres (`rebuild_redis.py`). Redis Streams er neste steg hvis consumer groups trengs |
| **Caching** | Modeller: lastet én gang per worker-prosess. Idempotens: sha256 + 5-min-bøtte i Postgres. JWKS-nøkler: cachet i prosess |
| **Retry** | 3 forsøk med backoff 1s/3s/10s per steg, teller i payload |
| **DLQ** | `dead_letter_queue`-tabell (payload-snapshot + feiltype) + Redis-speil + `FAILED`-state + audit |
| **Recovery** | ReconciliationWorker: stuck (utløpt lås), ghost (i Postgres, ikke Redis), tapt (UPLOADED > 5 min) |
| **Monitoring** | Prometheus (`nav_jobber_behandlet_total`, `nav_jobb_varighet_sekunder`, API-latens) + Grafana. Alarmforslag: DLQ-rate > 0, kølengde > 500, p95 OCR > 30 s |
| **Logging** | Strukturert stdout → Loki + Promtail (compose-profil `overvaaking`); i produksjon: institusjonens stack (NAIS har Loki innebygd) |
| **HA** | Alle stateless-tjenester replicas ≥ 2; Postgres med replika + WAL-arkivering i produksjon; Redis med AOF (tap tåles — rebuildes) |

## Beste praksis brukt (store systemer)

- **Single source of truth**: kø kan alltid gjenoppbygges fra Postgres
- **Commit før push**: aldri melding i kø uten committet tilstand
- **Idempotente steg**: re-kjøring er ufarlig (lås + tilstandsmaskin)
- **Backpressure**: KEDA skalerer på kølengde i stedet for CPU
- **Graceful degradation**: OCR uten modell → konfidens 0 → manuell
  gjennomgang; metrikker uten prometheus-client → no-op
- **Skille compute-profiler**: GPU-workers (ocr/nlp) skalerer uavhengig
  av CPU-workers (preprocess/routing)
- **Human-in-the-loop**: lav konfidens ruter til mennesker, korreksjoner
  forbedrer modellen — datasvinghjul
