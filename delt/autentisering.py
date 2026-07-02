"""
Autentisering for API-tjenestene.

AUTH_MODUS styrer mekanismen:
  api_nokkel (standard) — statisk X-API-Key sammenlignes mot API_NOKKEL
                          (konstant-tid-sammenligning mot timing-angrep)
  oidc                  — Bearer-token (JWT) valideres mot en OIDC-utsteder
                          (Azure AD, Maskinporten, Keycloak, …)

OIDC-miljøvariabler:
  OIDC_JWKS_URL  — utstederens JWKS-endepunkt
                   (f.eks. https://login.microsoftonline.com/<tenant>/discovery/v2.0/keys)
  OIDC_ISSUER    — forventet «iss»-claim
  OIDC_AUDIENCE  — forventet «aud»-claim
"""
import os
import hmac
import logging

logger = logging.getLogger(__name__)

_jwk_klient = None


def auth_modus() -> str:
    return os.environ.get("AUTH_MODUS", "api_nokkel")


def _hent_jwk_klient():
    """Lazy-initialisert JWKS-klient med innebygd nøkkel-cache."""
    global _jwk_klient
    if _jwk_klient is None:
        import jwt
        _jwk_klient = jwt.PyJWKClient(os.environ["OIDC_JWKS_URL"], cache_keys=True)
    return _jwk_klient


def valider_oidc_token(token: str) -> dict:
    """Validerer JWT (signatur, utløp, issuer, audience). Kaster ved feil."""
    import jwt
    signeringsnokkel = _hent_jwk_klient().get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signeringsnokkel.key,
        algorithms=["RS256"],
        audience=os.environ["OIDC_AUDIENCE"],
        issuer=os.environ["OIDC_ISSUER"],
    )


def sjekk_forespoersel(headers, api_nokkel: str):
    """
    Autentiserer én forespørsel. Returnerer None hvis OK,
    ellers en feilmelding som skal gis med 401.
    """
    if auth_modus() == "oidc":
        auth = headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return "Manglende Bearer-token"
        try:
            valider_oidc_token(auth[len("Bearer "):])
            return None
        except Exception as exc:
            logger.warning("OIDC-validering feilet: %s", exc)
            return "Ugyldig token"

    # api_nokkel-modus: tom nøkkel = åpen (utvikling) — advares ved oppstart
    if not api_nokkel:
        return None
    gitt = headers.get("X-API-Key", "")
    if hmac.compare_digest(gitt.encode(), api_nokkel.encode()):
        return None
    return "Ugyldig eller manglende API-nøkkel"
