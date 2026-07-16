# Fase 0 — Filinventar (Deep Audit)

**Generert:** 2026-07-16 · **Metode:** deterministisk skann (`os.walk` + import-analyse av testfiler) — ikke manuell opptelling. Ekskludert: `.git`, `__pycache__`, `modeller/` (AI-vekter), `data/`, `.claude/`.

## Nøkkeltall

| Metrikk | Verdi |
|---|---|
| Filer totalt (kode/konfig/docs) | 156 |
| Linjer totalt | 14,815 |
| Python-filer | 96 |
| Python produksjonsfiler | 68 |
| — med koblet test (via import) | 26 |
| — uten koblet test | 42 |

> **Merk om testkobling:** koblingen er utledet av hvilke moduler testfilene faktisk importerer. Integrasjonstester (`test_integrasjon_lokal.py`) tester tjenester over HTTP/Redis uten å importere modulene — de fanges IKKE av denne kolonnen. Reell dekning vurderes i fase 6.

## worker (V2.1) (18 filer, 2,094 linjer)

| Fil | Linjer | Koblet test |
|---|---|---|
| `tjenester/workers/lag2_nlp/lag2.py` | 497 | test_llm_klient.py |
| `tjenester/workers/reconciliation/reconciliation_worker.py` | 487 | test_integrasjon_lokal.py |
| `tjenester/workers/base_worker.py` | 437 | test_integrasjon_lokal.py |
| `tjenester/workers/lag3_routing/lag3.py` | 189 | test_integrasjon_lokal.py |
| `tjenester/workers/lag0_preprocessing/lag0.py` | 169 | test_integrasjon_lokal.py |
| `tjenester/workers/lag1_ocr/lag1.py` | 162 | test_integrasjon_lokal.py |
| `tjenester/workers/kfp_steg.py` | 108 | test_integrasjon_lokal.py |
| `tjenester/workers/lag2_nlp/Dockerfile` | 12 | n/a |
| `tjenester/workers/lag1_ocr/Dockerfile` | 11 | n/a |
| `tjenester/workers/reconciliation/Dockerfile` | 8 | n/a |
| `tjenester/workers/lag0_preprocessing/Dockerfile` | 7 | n/a |
| `tjenester/workers/lag3_routing/Dockerfile` | 7 | n/a |
| `tjenester/workers/__init__.py` | 0 | — |
| `tjenester/workers/lag0_preprocessing/__init__.py` | 0 | — |
| `tjenester/workers/lag1_ocr/__init__.py` | 0 | — |
| `tjenester/workers/lag2_nlp/__init__.py` | 0 | — |
| `tjenester/workers/lag3_routing/__init__.py` | 0 | — |
| `tjenester/workers/reconciliation/__init__.py` | 0 | — |

## api (10 filer, 1,205 linjer)

| Fil | Linjer | Koblet test |
|---|---|---|
| `tjenester/api/ruter/last_opp.py` | 684 | test_integrasjon_lokal.py |
| `tjenester/api/ruter/sporsmal.py` | 253 | test_sporsmal.py, test_sporsmal_regler.py |
| `tjenester/api/hoved.py` | 148 | test_sok_startup_resilience.py |
| `tjenester/api/ruter/gjennomgang.py` | 49 | — |
| `tjenester/api/ruter/sok.py` | 26 | — |
| `tjenester/api/Dockerfile` | 19 | n/a |
| `tjenester/api/helsesjekk.py` | 14 | — |
| `tjenester/api/krav.txt` | 12 | n/a |
| `tjenester/api/__init__.py` | 0 | — |
| `tjenester/api/ruter/__init__.py` | 0 | — |

## sok (5 filer, 487 linjer)

| Fil | Linjer | Koblet test |
|---|---|---|
| `tjenester/sok/hoved.py` | 392 | test_sok_startup_resilience.py |
| `tjenester/sok/fusjon.py` | 58 | test_audit_fikser.py |
| `tjenester/sok/helsesjekk.py` | 14 | — |
| `tjenester/sok/Dockerfile` | 13 | n/a |
| `tjenester/sok/krav.txt` | 10 | n/a |

## drift (2 filer, 17 linjer)

| Fil | Linjer | Koblet test |
|---|---|---|
| `tjenester/backup/Dockerfile` | 12 | n/a |
| `tjenester/oppbevaring/Dockerfile` | 5 | n/a |

## delt (7 filer, 669 linjer)

| Fil | Linjer | Koblet test |
|---|---|---|
| `delt/tekstuttrekk.py` | 274 | test_tekstuttrekk.py |
| `delt/skjemaer.py` | 108 | test_contract_compatibility.py |
| `delt/metrikker.py` | 86 | — |
| `delt/autentisering.py` | 84 | test_audit_fikser.py, test_observabilitet_auth.py |
| `delt/konstanter.py` | 80 | test_contract_compatibility.py, test_sec_rel_obs.py, test_state_machine.py |
| `delt/verktøy.py` | 37 | test_audit_fikser.py |
| `delt/__init__.py` | 0 | — |

## skript (14 filer, 1,905 linjer)

| Fil | Linjer | Koblet test |
|---|---|---|
| `skript/sikkerhetskopi.py` | 372 | test_oppbevaring.py, test_sikkerhetskopi.py |
| `skript/oppbevaring.py` | 325 | test_oppbevaring.py |
| `skript/finjuster.py` | 254 | — |
| `skript/eksporter_fra_label_studio.py` | 179 | — |
| `skript/dlq_gjenoppta.py` | 151 | — |
| `skript/rebuild_redis.py` | 108 | — |
| `skript/konverter_til_layoutlmv3.py` | 106 | — |
| `skript/init_db.py` | 103 | — |
| `skript/lag_layoutlmv3_datasett.py` | 96 | — |
| `skript/send_til_label_studio.py` | 70 | — |
| `skript/oppsett.sh` | 63 | n/a |
| `skript/last_ned_modeller.py` | 40 | — |
| `skript/migrer_server.sh` | 19 | n/a |
| `skript/sjekk_helse.py` | 19 | — |

## config (3 filer, 128 linjer)

| Fil | Linjer | Koblet test |
|---|---|---|
| `config/config.yaml` | 88 | n/a |
| `config/config_loader.py` | 40 | test_config.py, test_hardening.py, test_integrasjon_lokal.py, test_validation_queue_mapping.py |
| `config/__init__.py` | 0 | — |

## legacy (39 filer, 1,855 linjer)

| Fil | Linjer | Koblet test |
|---|---|---|
| `tjenester/lag3_nlp/lag3.py` | 439 | test_integrasjon_lokal.py |
| `tjenester/nlp/hoved.py` | 279 | test_sok_startup_resilience.py |
| `tjenester/ocr/hoved.py` | 251 | test_sok_startup_resilience.py |
| `tjenester/lag2_ocr/lag2.py` | 174 | test_llm_klient.py |
| `tjenester/lag0_kvalitet/lag0.py` | 102 | test_integrasjon_lokal.py |
| `tjenester/lag4_validering/lag4.py` | 97 | — |
| `tjenester/lag1_klassifisering/lag1.py` | 88 | test_integrasjon_lokal.py |
| `tjenester/ruter/ruter.py` | 64 | — |
| `tjenester/ocr/klassifiserer.py` | 62 | — |
| `tjenester/lag5_kryssvalidering/lag5.py` | 57 | — |
| `tjenester/ocr/pipeline.yaml` | 40 | n/a |
| `tjenester/trening/Dockerfile` | 15 | n/a |
| `tjenester/nlp/helsesjekk.py` | 14 | — |
| `tjenester/ocr/helsesjekk.py` | 14 | — |
| `tjenester/ocr/Dockerfile` | 13 | n/a |
| `tjenester/ocr/krav.txt` | 13 | n/a |
| `tjenester/nlp/krav.txt` | 11 | n/a |
| `tjenester/nlp/Dockerfile` | 10 | n/a |
| `tjenester/lag0_kvalitet/Dockerfile` | 6 | n/a |
| `tjenester/lag0_kvalitet/helsesjekk.py` | 6 | — |
| `tjenester/lag1_klassifisering/Dockerfile` | 6 | n/a |
| `tjenester/lag1_klassifisering/helsesjekk.py` | 6 | — |
| `tjenester/lag2_ocr/Dockerfile` | 6 | n/a |
| `tjenester/lag2_ocr/helsesjekk.py` | 6 | — |
| `tjenester/lag3_nlp/Dockerfile` | 6 | n/a |
| `tjenester/lag3_nlp/helsesjekk.py` | 6 | — |
| `tjenester/lag4_validering/Dockerfile` | 6 | n/a |
| `tjenester/lag4_validering/helsesjekk.py` | 6 | — |
| `tjenester/lag5_kryssvalidering/Dockerfile` | 6 | n/a |
| `tjenester/lag5_kryssvalidering/helsesjekk.py` | 6 | — |
| `tjenester/ruter/Dockerfile` | 6 | n/a |
| `tjenester/ruter/helsesjekk.py` | 6 | — |
| `tjenester/lag0_kvalitet/krav.txt` | 4 | n/a |
| `tjenester/lag1_klassifisering/krav.txt` | 4 | n/a |
| `tjenester/lag2_ocr/krav.txt` | 4 | n/a |
| `tjenester/lag3_nlp/krav.txt` | 4 | n/a |
| `tjenester/lag4_validering/krav.txt` | 4 | n/a |
| `tjenester/lag5_kryssvalidering/krav.txt` | 4 | n/a |
| `tjenester/ruter/krav.txt` | 4 | n/a |

## test (28 filer, 3,920 linjer)

| Fil | Linjer | Koblet test |
|---|---|---|
| `tester/test_integrasjon_lokal.py` | 899 | — |
| `tester/test_contract_compatibility.py` | 244 | — |
| `tester/test_hardening.py` | 236 | — |
| `tester/test_audit_fikser.py` | 235 | — |
| `tester/test_tekstuttrekk.py` | 213 | — |
| `tester/test_sec_rel_obs.py` | 206 | — |
| `tester/test_kubeflow_modus.py` | 166 | — |
| `tester/test_observabilitet_auth.py` | 156 | — |
| `tester/test_reconciliation_re_koe.py` | 155 | — |
| `tester/test_reconciliation_audit_atomicity.py` | 145 | — |
| `tester/test_sikkerhetskopi.py` | 107 | — |
| `tester/test_sok_startup_resilience.py` | 105 | — |
| `tester/test_reconciliation.py` | 96 | — |
| `tester/test_validation_queue_mapping.py` | 92 | — |
| `tester/test_contracts.py` | 87 | — |
| `tester/test_oppbevaring.py` | 85 | — |
| `tester/test_llm_klient.py` | 76 | — |
| `tester/test_sporsmal.py` | 72 | — |
| `tester/test_validation.py` | 70 | — |
| `tester/test_lag4.py` | 68 | — |
| `tester/test_ruter.py` | 68 | — |
| `tester/test_routing_decisions.py` | 65 | — |
| `tester/test_sporsmal_regler.py` | 58 | — |
| `tester/test_state_machine.py` | 57 | — |
| `tester/test_dlq.py` | 53 | — |
| `tester/test_idempotency.py` | 39 | — |
| `tester/test_lag0.py` | 39 | — |
| `tester/test_config.py` | 28 | — |

## k8s (18 filer, 1,000 linjer)

| Fil | Linjer | Koblet test |
|---|---|---|
| `k8s/13-workers.yaml` | 180 | n/a |
| `k8s/10-api.yaml` | 81 | n/a |
| `k8s/15-sikkerhetskopi.yaml` | 63 | n/a |
| `k8s/05-etcd.yaml` | 60 | n/a |
| `k8s/16-llm.yaml` | 58 | n/a |
| `k8s/03-postgres.yaml` | 57 | n/a |
| `k8s/09-sok.yaml` | 57 | n/a |
| `k8s/14-autoskalering.yaml` | 56 | n/a |
| `k8s/06-minio.yaml` | 55 | n/a |
| `k8s/08-label-studio.yaml` | 55 | n/a |
| `k8s/07-milvus.yaml` | 53 | n/a |
| `k8s/17-oppbevaring.yaml` | 52 | n/a |
| `k8s/04-redis.yaml` | 49 | n/a |
| `k8s/11-reconciliation.yaml` | 36 | n/a |
| `k8s/kustomization.yaml` | 33 | n/a |
| `k8s/02-pvc.yaml` | 22 | n/a |
| `k8s/12-init-db-jobb.yaml` | 22 | n/a |
| `k8s/01-hemmeligheter.yaml` | 11 | n/a |

## kubeflow (4 filer, 506 linjer)

| Fil | Linjer | Koblet test |
|---|---|---|
| `kubeflow/dokument_pipeline.yaml` | 221 | n/a |
| `kubeflow/trenings_pipeline.yaml` | 125 | n/a |
| `kubeflow/dokument_pipeline.py` | 89 | — |
| `kubeflow/trenings_pipeline.py` | 71 | — |

## overvaaking (3 filer, 49 linjer)

| Fil | Linjer | Koblet test |
|---|---|---|
| `overvaaking/promtail.yml` | 19 | n/a |
| `overvaaking/prometheus.yml` | 18 | n/a |
| `overvaaking/grafana-datasource.yml` | 12 | n/a |

## rot (5 filer, 980 linjer)

| Fil | Linjer | Koblet test |
|---|---|---|
| `docker-compose.yml` | 587 | n/a |
| `Makefile` | 216 | n/a |
| `pipeline_dashboard/pipeline.py` | 117 | — |
| `pipeline_dashboard/app.py` | 58 | — |
| `pipeline_dashboard/krav.txt` | 2 | n/a |

## Største filer (kompleksitets-hotspots → fase 6)

| Fil | Linjer |
|---|---|
| `tester/test_integrasjon_lokal.py` | 899 |
| `tjenester/api/ruter/last_opp.py` | 684 |
| `tjenester/workers/lag2_nlp/lag2.py` | 497 |
| `tjenester/workers/reconciliation/reconciliation_worker.py` | 487 |
| `tjenester/lag3_nlp/lag3.py` | 439 |
| `tjenester/workers/base_worker.py` | 437 |
| `tjenester/sok/hoved.py` | 392 |
| `skript/sikkerhetskopi.py` | 372 |
| `skript/oppbevaring.py` | 325 |
| `tjenester/nlp/hoved.py` | 279 |

## Python-produksjonsfiler uten koblet enhetstest

| Fil | Linjer | Kategori | Kommentar |
|---|---|---|---|
| `tjenester/api/ruter/gjennomgang.py` | 49 | api | **aktiv kode — vurderes i fase 6** |
| `tjenester/api/ruter/sok.py` | 26 | api | **aktiv kode — vurderes i fase 6** |
| `tjenester/api/helsesjekk.py` | 14 | api | triviell |
| `tjenester/api/__init__.py` | 0 | api | triviell |
| `tjenester/api/ruter/__init__.py` | 0 | api | triviell |
| `config/__init__.py` | 0 | config | triviell |
| `delt/metrikker.py` | 86 | delt |  |
| `delt/__init__.py` | 0 | delt | triviell |
| `kubeflow/dokument_pipeline.py` | 89 | kubeflow |  |
| `kubeflow/trenings_pipeline.py` | 71 | kubeflow |  |
| `tjenester/lag4_validering/lag4.py` | 97 | legacy | null trafikk i V2.1 (README: legacy-lag) |
| `tjenester/ruter/ruter.py` | 64 | legacy | null trafikk i V2.1 (README: legacy-lag) |
| `tjenester/ocr/klassifiserer.py` | 62 | legacy | null trafikk i V2.1 (README: legacy-lag) |
| `tjenester/lag5_kryssvalidering/lag5.py` | 57 | legacy | null trafikk i V2.1 (README: legacy-lag) |
| `tjenester/nlp/helsesjekk.py` | 14 | legacy | null trafikk i V2.1 (README: legacy-lag) |
| `tjenester/ocr/helsesjekk.py` | 14 | legacy | null trafikk i V2.1 (README: legacy-lag) |
| `tjenester/lag0_kvalitet/helsesjekk.py` | 6 | legacy | null trafikk i V2.1 (README: legacy-lag) |
| `tjenester/lag1_klassifisering/helsesjekk.py` | 6 | legacy | null trafikk i V2.1 (README: legacy-lag) |
| `tjenester/lag2_ocr/helsesjekk.py` | 6 | legacy | null trafikk i V2.1 (README: legacy-lag) |
| `tjenester/lag3_nlp/helsesjekk.py` | 6 | legacy | null trafikk i V2.1 (README: legacy-lag) |
| `tjenester/lag4_validering/helsesjekk.py` | 6 | legacy | null trafikk i V2.1 (README: legacy-lag) |
| `tjenester/lag5_kryssvalidering/helsesjekk.py` | 6 | legacy | null trafikk i V2.1 (README: legacy-lag) |
| `tjenester/ruter/helsesjekk.py` | 6 | legacy | null trafikk i V2.1 (README: legacy-lag) |
| `pipeline_dashboard/pipeline.py` | 117 | rot |  |
| `pipeline_dashboard/app.py` | 58 | rot |  |
| `skript/finjuster.py` | 254 | skript | **aktiv kode — vurderes i fase 6** |
| `skript/eksporter_fra_label_studio.py` | 179 | skript | **aktiv kode — vurderes i fase 6** |
| `skript/dlq_gjenoppta.py` | 151 | skript | **aktiv kode — vurderes i fase 6** |
| `skript/rebuild_redis.py` | 108 | skript | **aktiv kode — vurderes i fase 6** |
| `skript/konverter_til_layoutlmv3.py` | 106 | skript | **aktiv kode — vurderes i fase 6** |
| `skript/init_db.py` | 103 | skript | **aktiv kode — vurderes i fase 6** |
| `skript/lag_layoutlmv3_datasett.py` | 96 | skript | **aktiv kode — vurderes i fase 6** |
| `skript/send_til_label_studio.py` | 70 | skript | **aktiv kode — vurderes i fase 6** |
| `skript/last_ned_modeller.py` | 40 | skript | **aktiv kode — vurderes i fase 6** |
| `skript/sjekk_helse.py` | 19 | skript | **aktiv kode — vurderes i fase 6** |
| `tjenester/sok/helsesjekk.py` | 14 | sok | triviell |
| `tjenester/workers/__init__.py` | 0 | worker (V2.1) | triviell |
| `tjenester/workers/lag0_preprocessing/__init__.py` | 0 | worker (V2.1) | triviell |
| `tjenester/workers/lag1_ocr/__init__.py` | 0 | worker (V2.1) | triviell |
| `tjenester/workers/lag2_nlp/__init__.py` | 0 | worker (V2.1) | triviell |
| `tjenester/workers/lag3_routing/__init__.py` | 0 | worker (V2.1) | triviell |
| `tjenester/workers/reconciliation/__init__.py` | 0 | worker (V2.1) | triviell |

## Omfang per fase (avledet av inventaret)

| Fase | Filer i omfang |
|---|---|
| 1 Arkitektur/pipeline/state machine | `delt/konstanter.py`, `tjenester/workers/base_worker.py`, `tjenester/api/ruter/last_opp.py`, `docker-compose.yml`, README |
| 2 Workers/Redis/Postgres | `tjenester/workers/**` (18 filer), `skript/init_db.py`, `skript/rebuild_redis.py`, `skript/dlq_gjenoppta.py` |
| 3 OCR/NLP/uttrekk/søk | `tjenester/workers/lag1_ocr`, `lag2_nlp`, `delt/tekstuttrekk.py`, `delt/konstanter.py`, `tjenester/sok/**` (5 filer) |
| 4 API/sikkerhet/GDPR | `tjenester/api/**` (10 filer), `delt/autentisering.py`, `skript/oppbevaring.py`, `skript/sikkerhetskopi.py`, `.env.example`, `config/` |
| 5 Docker/K8s/ytelse/resiliens | alle Dockerfiler (10), `docker-compose.yml`, `k8s/**` (18), `overvaaking/**` |
| 6 Tester/kodekvalitet | `tester/**` (28), hotspots-listen over |

**Utenfor omfang (begrunnet):** `tjenester/` legacy-lag (39 filer, null trafikk i V2.1 iht. README — revideres kun for død-kode-funn i fase 6), `docs/` (dokumentasjon, ikke kjørbar).
