.PHONY: oppsett start stopp restart logger last-ned-modeller helse finjuster migrer sok last-opp label-studio eksporter-korreksjoner send-til-trening lag-datasett konverter-annotasjoner init-db rebuild-redis start-workers start-reconciliation test-state-machine test-idempotency k8s-bygg k8s-start k8s-stopp k8s-status k8s-init-db k8s-kopier-modeller kfp-installer kfp-kompiler kfp-ui

# Ett-kommando lokalt førstegangsoppsett: .env, datamapper, GPU-sjekk.
# Laster IKKE ned modeller (kjør last-ned-modeller separat, ~17 GB).
oppsett:
	bash skript/oppsett.sh

start:
	docker compose up -d

stopp:
	docker compose down

restart:
	docker compose restart

logger:
	docker compose logs -f

last-ned-modeller:
	python skript/last_ned_modeller.py

helse:
	python skript/sjekk_helse.py

finjuster:
	python skript/finjuster.py

migrer:
	docker compose down
	docker compose pull
	docker compose up --build -d

sok:
	curl -X POST http://localhost:8000/sok \
		-H "Content-Type: application/json" \
		-d '{"sporsmal": "$(SPORSMAL)"}'

last-opp:
	curl -X POST http://localhost:8000/last-opp -F "fil=@$(FIL)"

label-studio:
	open http://localhost:8080

eksporter-korreksjoner:
	python skript/eksporter_fra_label_studio.py

send-til-trening:
	python skript/eksporter_fra_label_studio.py && make finjuster

lag-datasett:
	python skript/lag_layoutlmv3_datasett.py

konverter-annotasjoner:
	python skript/konverter_til_layoutlmv3.py

# ─── Lagdelt arkitektur ─────────────────────────────────────────────────────

start-lag:
	docker compose up -d lag0 lag1 lag2 lag3 lag4 ruter redis milvus etcd minio label-studio

stopp-lag:
	docker compose stop lag0 lag1 lag2 lag3 lag4 lag5 ruter

start-kryssvalidering:
	docker compose --profile kryssvalidering up -d lag5

test:
	python -m pytest tester/ -v

helse-lag:
	@for port in 8010 8011 8012 8013 8014 8016; do \
		echo -n "Port $$port: "; \
		curl -sf http://localhost:$$port/helse | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null || echo "ikke tilgjengelig"; \
	done

ruter-prosesser:
	curl -s http://localhost:8016/helse

# ── Nye lag (fase 8) ─────────────────────────────────────────────────────────
start-lag0:
	docker compose up lag0 -d

start-lag1:
	docker compose up lag1 -d

start-lag2:
	docker compose up lag2 -d

start-lag3:
	docker compose up lag3 -d

start-lag4:
	docker compose up lag4 -d

start-lag5:
	docker compose up lag5 -d

start-ruter:
	docker compose up ruter -d

start-alle:
	docker compose up -d

start-ny:
	docker compose --profile "" up -d

test-lag:
	python3 -m pytest tester/test_lag$(N).py -v

test-alle-lag:
	python3 -m pytest tester/ -v

# ─── V2.1 kommandoer ────────────────────────────────────────────────────────

init-db:
	python skript/init_db.py

rebuild-redis:
	python skript/rebuild_redis.py

start-workers:
	docker compose up -d preprocessing_worker ocr_worker nlp_worker routing_worker

start-reconciliation:
	docker compose up -d reconciliation_worker

test-state-machine:
	python -m pytest tester/test_state_machine.py -v

test-idempotency:
	python -m pytest tester/test_idempotency.py -v



# ─── Kubernetes / Kubeflow (kubeflow-modus) ─────────────────────────────────

KFP_VERSJON ?= 2.2.0

k8s-bygg:
	docker build -t nav/api:lokal            -f tjenester/api/Dockerfile .
	docker build -t nav/sok:lokal            -f tjenester/sok/Dockerfile .
	docker build -t nav/lag0:lokal           -f tjenester/workers/lag0_preprocessing/Dockerfile .
	docker build -t nav/lag1:lokal           -f tjenester/workers/lag1_ocr/Dockerfile .
	docker build -t nav/lag2:lokal           -f tjenester/workers/lag2_nlp/Dockerfile .
	docker build -t nav/lag3:lokal           -f tjenester/workers/lag3_routing/Dockerfile .
	docker build -t nav/reconciliation:lokal -f tjenester/workers/reconciliation/Dockerfile .
	docker build -t nav/trening:lokal        -f tjenester/trening/Dockerfile .

kfp-installer:
	kubectl apply -k "github.com/kubeflow/pipelines/manifests/kustomize/cluster-scoped-resources?ref=$(KFP_VERSJON)"
	kubectl wait --for condition=established --timeout=60s crd/applications.app.k8s.io
	kubectl apply -k "github.com/kubeflow/pipelines/manifests/kustomize/env/platform-agnostic?ref=$(KFP_VERSJON)"

kfp-kompiler:
	python kubeflow/dokument_pipeline.py
	python kubeflow/trenings_pipeline.py

kfp-ui:
	kubectl port-forward -n kubeflow svc/ml-pipeline-ui 8888:80

k8s-start:
	kubectl apply -k k8s/

k8s-stopp:
	kubectl delete -k k8s/

k8s-status:
	kubectl get pods -n kubeflow

k8s-init-db:
	kubectl delete job nav-init-db -n kubeflow --ignore-not-found
	kubectl apply -n kubeflow -f k8s/12-init-db-jobb.yaml

# Kopierer lokale modeller (./modeller) inn i nav-modeller-PVC-en
k8s-kopier-modeller:
	kubectl delete pod modell-hjelper -n kubeflow --ignore-not-found
	kubectl run modell-hjelper -n kubeflow --image=busybox --restart=Never \
		--overrides='{"spec":{"containers":[{"name":"modell-hjelper","image":"busybox","command":["sleep","3600"],"volumeMounts":[{"name":"m","mountPath":"/modeller"}]}],"volumes":[{"name":"m","persistentVolumeClaim":{"claimName":"nav-modeller"}}]}}'
	kubectl wait --for=condition=Ready pod/modell-hjelper -n kubeflow --timeout=120s
	kubectl cp ./modeller kubeflow/modell-hjelper:/
	kubectl delete pod modell-hjelper -n kubeflow

# ─── Overvåking (Prometheus + Grafana) ──────────────────────────────────────

overvaaking:
	docker compose --profile overvaaking up -d prometheus grafana loki promtail
	@echo "Prometheus: http://localhost:9090 — Grafana: http://localhost:3000 (admin/admin)"
