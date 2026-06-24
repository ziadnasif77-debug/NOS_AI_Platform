# Refaktoreringsanalyse — NAV Archive Intelligence System

## 1. Funksjoner i `tjenester/ocr/hoved.py`

| Funksjon | Ansvar |
|---|---|
| `_oppdater_jobb(jobb_id, status, detaljer)` | Oppdaterer jobbstatus i Redis med 24 timers TTL |
| `_les_jobb_id(pdf_sti)` | Leser jobb_id fra sidecar-JSON generert av API ved opplasting |
| `pdf_til_bilde(pdf_sti, utgang_sti)` | Konverterer første PDF-side til PNG via PyMuPDF |
| `kjor_htrflow(pdf_sti, fil_id)` | Kjører HTRflow-pipeline for håndskrevne dokumenter |
| `kjor_marker(pdf_sti, fil_id)` | Kjører Marker-PDF for tabeller og komplekse layout |
| `kjor_paddleocr(bilde_sti, fil_id)` | Kjører PaddleOCR for trykte skjemaer, returnerer tokens+bokser for LayoutLMv3 |
| `kjor_ocr(pdf_sti, fil_id, dokumenttype, bilde_sti)` | Router til riktig OCR-modell basert på dokumenttype |
| `behandle_pdf(pdf_sti)` | Full pipeline-behandling: konverter→klassifiser→OCR→branch til NLP/Label Studio |
| `_send_til_nlp(fil_id, filnavn, dokumenttype, ocr_resultat)` | Sender dokument til NLP-tjenesten ved høy konfidens |
| `_send_til_label_studio(fil_id, pdf_sti, ocr_resultat)` | Sender dokument til Label Studio ved lav konfidens |
| `start_watchdog()` | Starter filesystem-watcher på inntak-mappen |
| `NyFilHaandterer.on_created` | Håndterer ny fil-event og starter behandling i egen tråd |

## 2. Funksjoner i `tjenester/nlp/hoved.py`

| Funksjon | Ansvar |
|---|---|
| `behandle(data)` | FastAPI-endepunkt: orkestrerer klassifisering og feltuttrekking |
| `_layoutlmv3_ekstraher(bilde_sti, tokens, bokser)` | Trekker ut feltdata (navn, fnr, dato, etc.) via LayoutLMv3 |
| `_trekk_ut_entiteter_ner(tekst)` | Fallback NER-uttrekking via NB-BERT-NER |
| `_klassifiser_dokument(tekst)` | Zero-shot klassifisering av dokumenttype, ytelse og utfall via NB-BERT |
| `_ekstraher_fylke(tekst)` | Søker etter norske fylkesnavn i tekst |
| `_borealis_analyse(tekst, klassifisering, entiteter)` | Genererer oppsummering og finn fylke via Borealis-4B LLM |
| `_send_til_sok(fil_id, tekst, data)` | Sender ferdig uttrukket data til søketjenesten for indeksering |

## 3. HTTP-kall mellom tjenester

| Fra | Til | Endepunkt | Formål |
|---|---|---|---|
| `ocr/hoved.py` | `nlp:8002` | `POST /behandle` | Send dokument til NLP ved høy OCR-konfidens |
| `ocr/hoved.py` | Label Studio | `POST /api/projects/{id}/import` | Send dokument til gjennomgang ved lav konfidens |
| `nlp/hoved.py` | `sok:8003` | `POST /indekser` | Indekser ferdig behandlet dokument i Milvus/BM25 |
| `api/hoved.py` | `ocr:8001` | `GET /helse` | Helsesjekk av OCR-tjeneste |
| `api/hoved.py` | `nlp:8002` | `GET /helse` | Helsesjekk av NLP-tjeneste |
| `api/hoved.py` | `sok:8003` | `GET /helse` | Helsesjekk av søketjeneste |
| `api/hoved.py` | `sok:8003` | `GET /statistikk` | Hent statistikk for søkeindeks |
| `api/hoved.py` | `sok:8003` | `POST /sok` | Videresend søkeforespørsel |
| `api/ruter/gjennomgang.py` | Label Studio | `GET /api/projects/` | Hent gjennomgangskø |
| `api/ruter/gjennomgang.py` | Label Studio | `POST /api/projects/{id}/import` | Send korreksjon til Label Studio |

## 4. Hardkodede verdier som skal til CONFIG

| Verdi | Hvor | CONFIG-nøkkel |
|---|---|---|
| `"85"` (konfidens terskel) | `ocr/hoved.py` linje 29 | `terskler.ocr_konfidens` |
| `"2"` (maks OCR-jobber) | `ocr/hoved.py` linje 31 | `gpu.maks_ocr_jobber` |
| `"http://nlp:8002"` | `ocr/hoved.py` linje 28 | `porter.lag3` (+ hostname) |
| `"/data/inntak"` | `ocr/hoved.py` linje 25 | `stier.inntak` |
| `"/data/behandlet"` | `ocr/hoved.py` linje 26 | `stier.behandlet` |
| `"/modeller"` | `ocr/hoved.py` linje 27 | `stier.modeller` |
| `"http://sok:8003"` | `nlp/hoved.py` linje 23 | `porter.lag_sok` |
| `"/modeller"` | `nlp/hoved.py` linje 22 | `stier.modeller` |
| `"cpu"` (GPU-enhet) | `nlp/hoved.py` linje 24 | `gpu.enhet` |
| `86400` (Redis TTL) | `ocr/hoved.py` linje 51 | `redis.ttl_sekunder` |
| `"redis://redis:6379/0"` | `ocr/hoved.py` via env | `redis.url` |
| `"1"` (Label Studio prosjekt-ID) | `send_til_label_studio.py` linje 13 | `label_studio.prosjekter.lag0` |
| `0.85` (standard terskel) | `delt/konstanter.py` linje 13 | `terskler.ocr_konfidens` |
| `8001` (OCR port) | `ocr/hoved.py` linje 371 | `porter.lag2` |
| `8002` (NLP port) | `nlp/hoved.py` linje 279 | `porter.lag3` |
| `8003` (søk port) | `sok/hoved.py` linje 222 | `porter.sok` |
| `"nb-bert"` | `nlp/hoved.py` linje 33 | `modeller.nb_bert` |
| `"nb-bert-ner"` | `nlp/hoved.py` linje 55 | `modeller.nb_bert_ner` |
| `"layoutlmv3"` | `nlp/hoved.py` linje 42 | `modeller.layoutlmv3` |
| `"borealis"` | `nlp/hoved.py` linje 62 | `modeller.borealis` |
| `"qwen3-embed"` | `sok/hoved.py` linje 64 | `modeller.qwen3` |
