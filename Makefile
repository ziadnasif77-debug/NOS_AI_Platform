# NAV Dokument-API — lokal server (native Windows + GPU)
# Ingen Docker: serveren kjører direkte med Python.

.PHONY: start klient test korpus modeller \
        finjuster eksporter-korreksjoner lag-datasett konverter-annotasjoner \
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
eksporter-korreksjoner:      ## Hent korreksjoner fra Label Studio → data/finjustering
	python skript/eksporter_fra_label_studio.py

lag-datasett:                ## Lag LayoutLMv3-datasett fra PDF-er
	python skript/lag_layoutlmv3_datasett.py

konverter-annotasjoner:      ## Konverter Label Studio-eksport → LayoutLMv3-format
	python skript/konverter_til_layoutlmv3.py

finjuster:                   ## Finjuster TrOCR + NB-BERT + LayoutLMv3
	python skript/finjuster.py

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
