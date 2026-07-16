# Virksomhetsregler for dokumentspørsmål (/dokument/{id}/sporsmal)
#
# HVORDAN DENNE FILEN VIRKER:
#   - Filen leses PÅ NYTT ved hvert eneste spørsmål — endringer gjelder
#     umiddelbart, ingen omstart nødvendig.
#   - Linjer som starter med «#» er kommentarer og sendes ALDRI til
#     modellen. Alt annet innhold sendes som strenge regler.
#   - Skriv én regel per linje (eller korte avsnitt). Nummerering er
#     valgfri — reglene nummereres automatisk i prompten.
#   - Reglene gjelder I TILLEGG til grunnreglene (svar kun fra
#     dokumentteksten, aldri gjett, JSON-format) og kan aldri
#     oppheve dem.
#
# HVA SLAGS REGLER VIRKER BEST (verifisert mot Borealis-4B):
#   ✓ Strenghetsregler: «er du usikker → funnet=false», «velg laveste
#     sidetall ved flere kandidater», «aldri forkortelser»
#   ✓ Utvalgsregler: hvilke kandidater som skal foretrekkes
#   ✗ Omskrivningsregler («fjern prefiks», «oversett») følges upålitelig —
#     grunnregelen om ordrett uthenting fra dokumentet vinner med vilje.
#     Trenger du transformasjon: gjør det i klienten, eller be om det
#     eksplisitt i selve spørsmålet.
#
# Redigér fritt under denne linjen: ────────────────────────────────

Svar alltid med KUN selve verdien — aldri en hel setning eller forklaring.

Er du usikker på svaret, sett funnet=false i stedet for å levere et usikkert svar.

Datoer skal alltid normaliseres til formatet dd.mm.yyyy.

Beløp skal alltid oppgis som rene tall uten «kr», mellomrom eller tusenskilletegn.

Finnes flere kandidater til svaret, velg den som står på lavest sidetall, og nevn i sitatet at flere kandidater finnes.

Ytelser skal alltid rapporteres med sitt fulle norske navn slik det står i dokumentet — aldri forkortelser eller omskrivninger.
