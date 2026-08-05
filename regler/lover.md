# Lovregister — hvilke lover vi slår opp i, og hvordan de skilles

Systemet har mer enn én folketrygdlov. De har LIKE paragrafnummer for
ULIKE ting, og en referanse uten lov er derfor tvetydig:

| Kapittel | 1966 (opphevet) | 1997 (gjeldende) |
|---|---|---|
| 3 | Sykepenger | Beregningsregler, trygdetid |
| 7 | Alderspensjon | Stønad ved gravferd |
| **8** | **Uførepensjon** | **Sykepenger** |
| **11** | **Yrkesskade** | **Arbeidsavklaringspenger** |
| **12** | Ugifte/skilte forsørgere | **Uføretrygd** |
| 14 | Krav om ytelser, saksbehandling | Svangerskap, fødsel og adopsjon |
| 19 | Ikrafttreden | Alderspensjon |

18 av kapitlene betyr noe annet i den ene loven enn i den andre. «§ 8-1»
er uførepensjon i 1966-loven og sykepenger i 1997-loven. Slår vi opp i
feil lov, får vi et svar som ser helt riktig ut — og det er den farlige
sorten.

**Derfor:** et paragrafoppslag SKAL oppgi hvilken lov det gjelder. Uten
lov svarer `delt/lover.py` med at referansen er flertydig og lister
begge tolkningene — den gjetter ikke.

---

## Slik legger du til en lov

1. Hent teksten:
   `python skript/hent_lovtekst.py <lovdata-url> data/lover/<navn>.md`
2. Legg til en blokk under, med samme felter.
3. Kjør `python -m pytest tester/test_lover.py -q`.

Feltene i en blokk er `nøkkel = verdi`, én per linje. Teksten til lovene
ligger i `data/lover/` (samme policy som modeller: for stor for git,
følger med når mappa kopieres) — registeret her er sporet, så en
ufullstendig kopi oppdages av testen i stedet for ved første oppslag.

---

[[lov:ftrl-1997]]
tittel = Lov om folketrygd (folketrygdloven)
kortnavn = folketrygdloven
lovdata_id = 1997-02-28-19
status = gjeldende
gjelder_fra = 1997-05-01
gjelder_til =
kilde = https://lovdata.no/dokument/NL/lov/1997-02-28-19
fil = data/lover/folketrygdloven-1997-gjeldende.md
merknad = Gjeldende folketrygdlov. Kapitlene navngir ytelsene: 4 dagpenger, 8 sykepenger, 11 arbeidsavklaringspenger, 12 uføretrygd, 14 foreldrepenger, 19/20 alderspensjon.
[[/lov:ftrl-1997]]

[[lov:ftrl-1966]]
tittel = Lov om folketrygd
kortnavn = folketrygdloven (1966)
lovdata_id = 1966-06-17-12
status = opphevet
gjelder_fra = 1967-01-01
gjelder_til = 1997-05-01
kilde = https://lovdata.no/dokument/NLO/lov/1966-06-17-12
fil = data/lover/folketrygdloven-1966-opphevet.md
merknad = OPPHEVET. Brukes bare til å forstå gamle dokumenter og vedtak fattet før mai 1997 — aldri som gjeldende rett.
[[/lov:ftrl-1966]]

---

## Hvilken lov gjelder for et dokument?

Er dokumentdatoen kjent, avgjør den: dokumenter datert før 1. mai 1997
hører til 1966-loven, senere til 1997-loven. `delt/lover.py` gjør dette
oppslaget med `lov_for_dato()`.

Er datoen ukjent, er svaret ukjent. Et vedtak vi ikke kan tidfeste, kan
ikke tolkes mot en bestemt lov uten å gjette — og en gjetning om
hjemmelen for et vedtak er verre enn ingen.
