.PHONY: start stopp restart logger last-ned-modeller helse finjuster migrer sok last-opp label-studio eksporter-korreksjoner send-til-trening

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
