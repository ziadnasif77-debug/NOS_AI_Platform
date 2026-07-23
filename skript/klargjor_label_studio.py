# -*- coding: utf-8 -*-
"""Klargjør Label Studio for auto-gjennomgang — idempotent engangsoppsett.

Gjør tre ting (og hopper over det som allerede finnes):
  1. Verifiserer API-nøkkelen (LABEL_STUDIO_API_KEY) mot serveren.
  2. Oppretter OCR-korreksjonsprosjektet med norsk grensesnitt der
     tekstfeltet er FORHÅNDSUTFYLT med maskinens lesing — den ansatte
     retter bare feilene og trykker Submit.
  3. Kobler til lokal fillagring (data/gjennomgang/bilder) så bildene
     auto-gjennomgangen legger der, vises i oppgavene.

Kjøres med prosjektets Python og miljøet fra oppstart\\lokal_env.bat:
    .pyruntime\\python.exe skript\\klargjor_label_studio.py
Skriver prosjekt-ID-en tilbake til oppstart\\lokal_env.bat.
"""
import io
import os
import re
import sys
from pathlib import Path

import requests

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROT = Path(__file__).resolve().parent.parent
LOKAL_ENV = ROT / "oppstart" / "lokal_env.bat"

LS_URL = os.environ.get("LABEL_STUDIO_URL", "http://localhost:8080")
LS_NOKKEL = os.environ.get("LABEL_STUDIO_API_KEY", "")
PROSJEKT_TITTEL = "OCR-korreksjon (norsk)"

# Profesjonelt oppsett etter Label Studios offisielle OCR-mal: STORT bilde
# (Image har maxWidth=750px som standard — derfor så bildet lite ut!) med
# zoom/lysstyrke/kontrast, valgfrie regionmarkeringer (Labels+Rectangle,
# som i malen bedrifter bruker), og en klistret høyrekolonne med det
# forhåndsutfylte korreksjonsfeltet. NB: kun ÉN TextArea — eksporten
# (eksporter_fra_label_studio) leser første result av type «textarea»,
# så regionverktøyene er bevisst uten perRegion-transkripsjon.
ETIKETT_KONFIG = """<View>
  <Header value="Rett maskinens lesing så den stemmer med dokumentbildet — Ctrl+Enter sender inn"/>
  <View style="display: flex; gap: 18px; align-items: flex-start;">
    <View style="flex: 64%; min-width: 55%;">
      <Image name="bilde" value="$bilde" width="100%" maxWidth="100%"
             zoom="true" zoomControl="true" defaultZoom="fit"
             rotateControl="true" brightnessControl="true" contrastControl="true"/>
    </View>
    <View style="flex: 36%; position: sticky; top: 12px;">
      <Header value="Maskinens lesing — konfidens: $konfidens %"/>
      <Collapse>
        <Panel value="Felter maskinen fant">
          <Text name="funn" value="Navn: $navn — Dato: $dato — Ytelse: $ytelse — Fylke: $fylke"/>
        </Panel>
        <Panel value="Rå maskinlesing (original)">
          <Text name="tekst" value="$tekst"/>
        </Panel>
      </Collapse>
      <Header value="Områder på bildet — forhåndsmerket av maskinen" size="4"/>
      <RectangleLabels name="omraade" toName="bilde" showInline="true"
                       strokeWidth="2" opacity="0.15">
        <Label value="Håndskrift" background="#ec4899"/>
        <Label value="Trykt tekst" background="#22c55e"/>
        <Label value="Uleselig" background="#ef4444"/>
        <Label value="Stempel/signatur" background="#f59e0b"/>
      </RectangleLabels>
      <Header value="Korrigert tekst — forhåndsutfylt, rett bare feilene" size="4"/>
      <TextArea name="transkripsjon" toName="bilde" value="$tekst"
                rows="14" editable="true" maxSubmissions="1"/>
    </View>
  </View>
</View>"""

# Reserve uten Collapse-taggen (i tilfelle LS-versjonen avviser den).
ETIKETT_KONFIG_ENKEL = ETIKETT_KONFIG.replace(
    "<Collapse>", "").replace("</Collapse>", "").replace(
    '<Panel value="Felter maskinen fant">',
    '<Header value="Felter maskinen fant" size="4"/>').replace(
    '<Panel value="Rå maskinlesing (original)">',
    '<Header value="Rå maskinlesing (original)" size="4"/>').replace(
    "</Panel>", "")


def _hoder() -> dict:
    return {"Authorization": f"Token {LS_NOKKEL}"}


def sjekk_nokkel() -> bool:
    svar = requests.get(f"{LS_URL}/api/projects/", headers=_hoder(), timeout=15)
    if svar.status_code == 401:
        print("[FEIL] API-nøkkelen ble avvist (401). Sjekk oppstart\\lokal_env.bat.")
        return False
    svar.raise_for_status()
    print(f"[OK] API-nøkkelen virker mot {LS_URL}")
    return True


def finn_eller_opprett_prosjekt() -> int:
    svar = requests.get(f"{LS_URL}/api/projects/", headers=_hoder(), timeout=15)
    svar.raise_for_status()
    for p in svar.json().get("results", []):
        if p.get("title") == PROSJEKT_TITTEL:
            print(f"[OK] Prosjektet finnes allerede (id {p['id']}) — oppdaterer grensesnittet")
            patch = requests.patch(f"{LS_URL}/api/projects/{p['id']}/", headers=_hoder(),
                                   json={"label_config": ETIKETT_KONFIG}, timeout=15)
            if not patch.ok:
                print(f"[ADV] Full konfig avvist ({patch.status_code}) — prøver uten Collapse")
                requests.patch(f"{LS_URL}/api/projects/{p['id']}/", headers=_hoder(),
                               json={"label_config": ETIKETT_KONFIG_ENKEL},
                               timeout=15).raise_for_status()
            return p["id"]
    svar = requests.post(
        f"{LS_URL}/api/projects/", headers=_hoder(), timeout=30,
        json={
            "title": PROSJEKT_TITTEL,
            "description": ("Dokumenter API-et leste dårlig (lav konfidens, håndskrift "
                            "eller tomt resultat). Rett teksten — den mater finjusteringen "
                            "av norhand automatisk."),
            "label_config": ETIKETT_KONFIG,
        })
    svar.raise_for_status()
    pid = svar.json()["id"]
    print(f"[OK] Opprettet prosjektet «{PROSJEKT_TITTEL}» (id {pid})")
    return pid


def koble_lokal_lagring(prosjekt_id: int) -> None:
    bilder = ROT / "data" / "gjennomgang" / "bilder"
    bilder.mkdir(parents=True, exist_ok=True)
    svar = requests.get(f"{LS_URL}/api/storages/localfiles?project={prosjekt_id}",
                        headers=_hoder(), timeout=15)
    if svar.ok and any(str(bilder).lower() in str(s.get("path", "")).lower()
                       for s in svar.json()):
        print("[OK] Lokal fillagring er allerede koblet")
        return
    svar = requests.post(
        f"{LS_URL}/api/storages/localfiles", headers=_hoder(), timeout=15,
        json={"project": prosjekt_id, "title": "gjennomgang-bilder",
              "path": str(bilder), "use_blob_urls": False})
    if svar.ok:
        print(f"[OK] Koblet lokal fillagring: {bilder}")
    else:
        # Ikke kritisk: /data/local-files/?d=... virker likevel når
        # LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED + DOCUMENT_ROOT er satt.
        print(f"[ADV] Klarte ikke å koble fillagring ({svar.status_code}): "
              f"{svar.text[:150]} — bildene vises trolig likevel (serving er på)")


def oppdater_lokal_env(prosjekt_id: int) -> None:
    if not LOKAL_ENV.is_file():
        print(f"[ADV] Fant ikke {LOKAL_ENV} — sett "
              f"LABEL_STUDIO_OCR_PROSJEKT_ID={prosjekt_id} selv.")
        return
    tekst = LOKAL_ENV.read_text(encoding="ascii")
    ny = re.sub(r'set "LABEL_STUDIO_OCR_PROSJEKT_ID=\d+"',
                f'set "LABEL_STUDIO_OCR_PROSJEKT_ID={prosjekt_id}"', tekst)
    if ny != tekst:
        LOKAL_ENV.write_text(ny, encoding="ascii")
        print(f"[OK] lokal_env.bat oppdatert: prosjekt-ID = {prosjekt_id}")
    else:
        print(f"[OK] lokal_env.bat hadde allerede prosjekt-ID {prosjekt_id}")


def main() -> int:
    if not LS_NOKKEL:
        print("[FEIL] LABEL_STUDIO_API_KEY er ikke satt. Kjør via en launcher som "
              "laster oppstart\\lokal_env.bat, eller sett variabelen selv.")
        return 1
    if not sjekk_nokkel():
        return 1
    pid = finn_eller_opprett_prosjekt()
    koble_lokal_lagring(pid)
    oppdater_lokal_env(pid)
    print("\nFerdig. Auto-gjennomgangen er klar: dårlige lesinger dukker opp i "
          f"{LS_URL}/projects/{pid} — forhåndsutfylt og klare til retting.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
