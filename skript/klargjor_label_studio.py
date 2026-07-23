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

ETIKETT_KONFIG = """<View>
  <Header value="Rett maskinens lesing så den stemmer med dokumentbildet"/>
  <View style="display: flex; gap: 16px; align-items: flex-start;">
    <View style="flex: 1; min-width: 45%;">
      <Image name="bilde" value="$bilde" zoom="true" zoomControl="true" rotateControl="true"/>
    </View>
    <View style="flex: 1;">
      <Header value="Maskinens lesing (konfidens: $konfidens %)"/>
      <Text name="tekst" value="$tekst"/>
      <Header value="Maskinen fant disse feltene"/>
      <Text name="funn" value="Navn: $navn — Dato: $dato — Ytelse: $ytelse — Fylke: $fylke"/>
      <Header value="Korrigert tekst — forhåndsutfylt, rett bare feilene"/>
      <TextArea name="transkripsjon" toName="bilde" value="$tekst"
                rows="12" editable="true" maxSubmissions="1"/>
    </View>
  </View>
</View>"""


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
            requests.patch(f"{LS_URL}/api/projects/{p['id']}/", headers=_hoder(),
                           json={"label_config": ETIKETT_KONFIG}, timeout=15).raise_for_status()
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
