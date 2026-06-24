.PHONY: start stopp restart logger last-ned-modeller helse finjuster migrer sok last-opp label-studio eksporter-korreksjoner send-til-trening lag-datasett konverter-annotasjoner

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
	bash skript/migrer_server.sh

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

