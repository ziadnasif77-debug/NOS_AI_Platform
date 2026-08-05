# Kanonisk skjema for `/dokument`

Formålet med dette dokumentet er å avgjøre FORMEN på svaret fra
`/dokument` før flere felter legges til. Uten en avgjort form vokser
svaret felt for felt til det blir stort, usammenhengende og umulig å
endre uten å bryte klienter.

Status: **implementert, `skjemaversjon: "1.0"`.** Seksjonsformen i §3
er den som svares i dag, i begge kontraktene. Feltreferansen ligger i
[endepunkter.md](endepunkter.md); reglene som håndhever den er
R71–R73, R79–R97 i [regler_lokal_api.md](regler_lokal_api.md).

Endres formen senere, går `skjemaversjon` opp — en klient skal kunne se
endringen på tallet, ikke oppdage den når noe brekker. Det holdt ikke
som løfte alene: `API_VERSJON` sto urørt på 1.3.0 gjennom 45 commits
mens hele `operasjoner`-kontrakten, `hjemmel` og `sammendrag` kom til.
Derfor ligger nøkkelsettet nå som fasit i
`tester/fasit_profilnokler.json`, og `test_kontraktsvakt.py` feiler når
det endres — versjonen kan ikke lenger glemmes i stillhet (R87).

**1.0 — ett navn per felt.** Underveis i utviklingen ble nye navn
lagt til ved siden av de gamle for ikke å bryte klienter. API-et var aldri utgitt, så de klientene
fantes ikke — og prisen var at hvert felt lå to steder med en vakttest
for hvert par. Ved utgivelse er de gamle navnene fjernet:

| Bruk | Fjernet |
|---|---|
| `part` | `eier` |
| `andre_fodselsnummer` | `andre_personer` |
| `sammendrag.konfidens` | `sammendrag.sikkerhet` |
| `part.grunnlag` | `part.sikkerhet` |
| `dekning.ytelse` | `ytelse.implementasjon` |
| `dokument.aarstall` | `dokument.ar` |

Nytt i samme omgang: `part.fastslatt` (fant vi personen — som ÉN boolsk
verdi), `dekning` (hva systemet leter etter ennå), `ytelser[]` og
`hjemler[]` (et dokument kan gjelde flere), og `{kode, term}`-par for
dokumenttype og ytelse.

---

## 1. Hva systemet ALLEREDE henter ut

Kartlagt mot koden, ikke mot hukommelsen. Dette er utgangspunktet — det
meste av ønskelista finnes fra før, spredt over tre ulike svarformer
(`felter`, `struktur`, `dokumentprofil`).

| Ønsket felt | Finnes? | Hvor i dag |
|---|---|---|
| `filnavn`, `antall_sider` | ✅ | `dokumentprofil` |
| `dokumentdato`, `dokument_ar`, `dokument_alder` | ✅ | `dokumentprofil` |
| `periode_start` / `periode_slutt` | ✅ | `dokumentprofil.dokumentdato_fra/til` |
| `dokumenttype` | ⚠️ | `struktur.dokument.dokumenttype` — **feilklassifiserer** (se §5) |
| `ytelse` | ⚠️ | `struktur.dokument.ytelse` finnes og traff «dagpenger»; `dokumentprofil.ytelse` er plassholder — **to kilder til samme faktum** |
| `saksnummer` | ✅ | `struktur.identifikatorer.saksnummer` |
| `fnr` (eierens) | ✅ | `dokumentprofil.eier` |
| andre fnr i dokumentet | ✅ | `dokumentprofil.andre_personer` |
| `navn` | ✅ | eierens navn; andre navn kun via `andre_personer` |
| `organisasjonsnummer` | ✅ | `struktur.identifikatorer` |
| `kontonummer`, `kid` | ✅ | `struktur.identifikatorer` |
| `telefon`, `epost` | ✅ | `struktur.kontakt` |
| `adresse`, `postnummer`, `poststed` | ⚠️ | `struktur.adresser` — **feillesing** (se §5) |
| `belop`, `totalbelop` | ✅ | `struktur.belop`, `finn_totalbelop` |
| `forfallsdato`, `utbetalingsdato` | ✅ | datotypene finnes |
| QR / strekkode med side | ✅ | `dokumentprofil.koder` |
| stempel + `stempel_dato` | ✅ | `dokumentprofil.stempel_datoer` |
| håndskrift | ✅ | `handskrift` |
| `ocr_brukt`, OCR-kvalitet | ✅ | `kvalitet` |
| `fylke`, `kontornavn`, `sprak` | ✅ | `struktur.dokument` |
| `journalnummer`, `vedtaksnummer`, `referansenummer` | ❌ | mangler |
| `avsender`, `mottaker` | ❌ | mangler som egne felter |
| `arbeidsgiver`, `stilling`, `stillingsprosent` | ❌ | mangler |
| `lønn`, `inntekt`, `årsinntekt` | ❌ | mangler |
| `dagsats`, `månedsbeløp` | ❌ | mangler |
| `innvilget`/`avslått`/`stanset` | ❌ | mangler |
| `gyldig_fra` / `gyldig_til` (vedtakets) | ⚠️ | datotypene finnes, men er ikke skilt fra andre perioder |
| `kommune`, `fødselsdato`, `alder` (person) | ❌ | mangler (fødselsdato kan avledes av fnr) |
| `blanke_sider`, `uleselige_sider` | ❌ | mangler |
| `signatur_side`, `stempel_side` | ⚠️ | stempel har side; signatur ikke |
| `vedlegg` | ❌ | mangler |

**Hovedfunnet:** problemet er ikke at det mangler uttrekk. Problemet er
at det samme faktumet finnes tre steder i tre former — og at `ytelse`
allerede har to konkurrerende kilder etter én dag.

---

## 2. Prinsipper skjemaet skal bygge på

1. **Alle nøkler alltid til stede.** Tomt er `null` / `[]`, aldri en
   manglende nøkkel. En klient som må sjekke om feltet finnes før den
   leser det, har ingen kontrakt. (Samme regel som R44.)
2. **Ett faktum, ett sted.** Finnes `ytelse` i profilen, skal den ikke
   også ligge i `struktur` med en annen verdi. Duplikater blir
   motstridende — det er akkurat slik en API-er blir «stor og
   selvmotsigende».
3. **`null` framfor gjetning**, alltid med en begrunnelse ved siden av.
4. **Seksjoner, ikke ett flatt kart.** Et flatt kart med 80 felter er
   ikke utvidbart; seksjoner kan vokse uavhengig.
5. **Bevis der gjetning er farlig.** Fødselsnummer, datoer og beløp får
   `sikkerhet` + `begrunnelse`. Resten holdes flatt og lesbart —
   konvolutt rundt HVERT felt dobler svaret uten å gi verdi.
6. **Deterministisk som standard.** Profilen skal virke når Borealis er
   nede. Felter som KREVER modellen merkes, og er aldri stille null.

---

## 3. Forslag til kanonisk form

```jsonc
{
  "ok": true,
  "skjemaversjon": "1.0",          // profilens EGEN versjon, uavhengig av api-versjonen

  "fil": {
    "filnavn": "vedtak.pdf",
    "antall_sider": 10,
    "filtype": "pdf",
    "blanke_sider": [7],
    "uleselige_sider": []
  },

  "eier": {                         // personen dokumentet GJELDER (R69)
    "navn": "Ola Nordmann",
    "fnr": "12345678910",
    "fodselsdato": "1990-01-01",    // avledet av fnr når det er bevist
    "sikkerhet": "merket",
    "begrunnelse": "…"
  },

  "andre_personer": [               // ALDRI sammenblandet med eier
    {"navn": "Kari Hansen", "fnr": "…", "rolle": "saksbehandler", "etikett": "Saksbehandler"}
  ],

  "dokument": {
    "type": "vedtak",
    "kategori": null,
    "tittel": "Vedtak om dagpenger",
    "sprak": "norsk",
    "dato": "2026-05-08",
    "dato_norsk": "08.05.2026",
    "ar": 2026,
    "alder": {"dager": 810, "tekst": "2 år og 2 måneder gammelt", "fremtidig": false},
    "periode_start": "2025-01-01",  // hva dokumentet GJELDER FOR
    "periode_slutt": "2025-12-31",
    "spenn_fra": null,              // bunke: flere daterte dokumenter
    "spenn_til": null,
    "flere_dokumenter": false,
    "dato_sikkerhet": "hoy",
    "dato_begrunnelse": "etiketten «Vedtaksdato» står rett før datoen",
    "avsender": "NAV Arbeid og ytelser",
    "mottaker": null
  },

  "sak": {
    "saksnummer": "4417820",
    "journalnummer": null,
    "dokumentnummer": null,
    "referanse": null,
    "vedtaksnummer": null,
    "sakstype": null
  },

  "ytelse": {                       // reglene kommer senere — formen står klar
    "navn": null,
    "type": null,
    "utfall": null,                 // innvilget / avslatt / endret / stanset
    "gyldig_fra": null,
    "gyldig_til": null,
    "status": "ikke_implementert"
  },

  "okonomi": {
    "totalbelop": 24680.00,
    "dagsats": null,
    "manedsbelop": null,
    "valuta": "NOK",
    "kontonummer": ["12345678910"],
    "kid": ["1002345678911"],
    "forfallsdato": "2026-06-24",
    "utbetalingsdato": null
  },

  "arbeid": {
    "arbeidsgiver": null,
    "organisasjonsnummer": ["923609016"],
    "stilling": null,
    "stillingsprosent": null,
    "startdato": null,
    "sluttdato": null,
    "inntekt": null
  },

  "kontakt": {
    "telefoner": ["22222222"],
    "eposter": ["ola@example.no"],
    "adresser": [{"gate": "Storgata 12", "postnummer": "0181", "poststed": "OSLO", "kommune": null}]
  },

  "koder": {
    "lest": true,
    "qr": [{"side": 1, "verdi": "…", "type": "QRCODE"}],
    "strekkode": [{"side": 3, "verdi": "…", "type": "CODE128"}],
    "qr_kode_side": 1,
    "strekkode_side": 3
  },

  "visuelt": {
    "stempel_datoer": [{"dato": "2026-05-20", "side": 2, "type": "mottatt"}],
    "stempel_sider": [2],
    "signatur_sider": [],
    "handskrift_funnet": false,
    "vedlegg": []
  },

  "kvalitet": {
    "ocr_brukt": true,
    "ocr_motorer": {},
    "ocr_konfidens": 0.91,
    "tekstlag": false,
    "advarsler": []
  }
}
```

---

## 4. Hva forslaget svarer på

- **Fødselsnummer:** `eier.fnr` er dokumentets. Alle andre ligger i
  `andre_personer` — atskilt, med rolle. Dette er allerede implementert.
- **Tre datofelter blandes ikke:** `dokument.dato` (dokumentets egen),
  `dokument.periode_*` (hva det gjelder for), `dokument.spenn_*` (bunke).
- **`ytelse` får ÉN kilde.** `struktur.dokument.ytelse` avvikles til
  fordel for `ytelse`-seksjonen, så de to ikke kan si ulike ting.
- **Seksjonene kan vokse** uten å røre resten av kontrakten.
- **`skjemaversjon`** gjør en framtidig endring synlig for klienten i
  stedet for å skje i stillhet.

---

## 5. To ekte feil funnet under kartleggingen — RETTET

Begge var eldre enn dette arbeidet. De er rettet (R72/R73) med tester i
`tester/test_saksfelter.py`; beskrivelsen står igjen fordi den forklarer
hvorfor reglene ser ut som de gjør:

**a) `struktur.adresser` leser feil.** På et vanlig NAV-brev ble
resultatet:

```json
{"gate": "Fnr: 12345678910", "postnummer": "0181", "poststed": "OSLO"}
{"gate": "Telefon: 22 22 22 22  E-post: …", "postnummer": "1000", "poststed": "AS"}
```

Gata er hentet fra linja over postnummeret uten å sjekke om den ER en
gateadresse, og «Rema 1000 AS» ble lest som postnummer 1000 i poststed
AS. En klient som fyller et adressefelt fra dette, får søppel.

**b) `struktur.dokument.dokumenttype` feilklassifiserer.** Et vedtaks-
brev med «Vedtak om dagpenger» i tittelen ble klassifisert som
`faktura` — trolig fordi beløp og forfallsdato veier tyngre enn
tittelen.

---

## 6. Anbefaling

1. **Avgjør formen først** (dette dokumentet), deretter felter.
2. **Rett de to feilene i §5** før flere felter bygger på dem.
3. **Legg til felter seksjonsvis**, med tester per felt, i denne
   rekkefølgen etter nytte: `sak` → `okonomi` → `visuelt` →
   `arbeid` → `ytelse` (når reglene kommer).
4. **Ikke** la `/dokument` returnere alt `struktur` gjør. Profilen er
   dokumentets identitet; `struktur` og `/uttrekk` er totaluttrekket.
   Overlapper de, må de holdes i takt for alltid.
