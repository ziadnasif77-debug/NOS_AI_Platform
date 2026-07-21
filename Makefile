# NAV Dokument-API — lokal server (native Windows + GPU)
# Ingen Docker: serveren kjører direkte med Python.

.PHONY: start klient test korpus modeller \
        trening eksporter-korreksjoner finjuster valider rull-tilbake \
        rydd prefect-server prefect-kjor \
        pakk-offline installer-offline sjekk-miljo lovtekst

# ─── Server og klient ────────────────────────────────────────────────
start:                       ## Start dokument-API-et på :8600
	python skript/dokument_api.py

klient:                      ## Start GUI-klienten
	python skript/api_klient_gui.py

# ─── Modeller ────────────────────────────────────────────────────────
modeller:                    ## Last ned AI-modellene (én gang)
	python skript/last_ned_modeller.py

# ─── Treningsløkke (manuell modellforbedring) ────────────────────────
trening:                     ## Hele løkken: eksporter → finjuster → kvalitetsport
	python skript/kjor_treningslop.py

eksporter-korreksjoner:      ## Bare hent korreksjoner fra Label Studio → data/finjustering
	python skript/eksporter_fra_label_studio.py

finjuster:                   ## Bare tren en kandidat-modell (ikke live)
	python skript/finjuster.py

valider:                     ## Kvalitetsport: mål kandidat mot live (CER)
	python skript/valider_modell.py

rull-tilbake:                ## Gå tilbake til forrige norhand-modell
	python skript/valider_modell.py --rull-tilbake

# ─── Oppbevaring (GDPR) ──────────────────────────────────────────────
rydd:                        ## Tørrkjør rydding av gamle gjennomgangsbilder (legg til ARGS=--slett)
	python skript/rydd_gjennomgang.py $(ARGS)

# ─── Prefect (kontroll + observabilitet av treningsløkka) ────────────
prefect-server:              ## Start Prefect-UI-et på http://127.0.0.1:4200
	.venv-prefect/Scripts/prefect server start

prefect-kjor:                ## Kjør treningsløkka som Prefect-flyt (ser hvor det evt. feiler)
	.venv-prefect/Scripts/python skript/prefect_flyt.py

# ─── Test ────────────────────────────────────────────────────────────
test:                        ## Kjør enhetstestene (stopp serveren først — GPU deles)
	python -m pytest tester/ -q

korpus:                      ## Regresjonskorpus: ekte dokumenter mot fasit
	python skript/kjor_korpus.py

# ─── Offline-distribusjon (isolert server) ───────────────────────────
pakk-offline:                ## Pakk alt for en frakoblet server → offline_pakke/
	python skript/pakk_for_offline.py

installer-offline:           ## Installer wheels uten internett (på serveren)
	python skript/installer_offline.py

sjekk-miljo:                 ## Verifiser Python/GPU/DLL/modeller
	python skript/sjekk_miljo.py

# ─── Verktøy ─────────────────────────────────────────────────────────
lovtekst:                    ## Hent en lov fra Lovdata (LOV="...")
	python skript/hent_lovtekst.py "$(LOV)"
