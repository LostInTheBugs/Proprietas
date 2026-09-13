"""Chiffrement des secrets 2FA et hachage des codes de secours.

La clé de chiffrement (Fernet) et la clé de hachage sont DÉRIVÉES de
COPRO_SECRET_KEY : si cette clé change, les secrets TOTP existants deviennent
illisibles — les comptes doivent ré-enrôler leur double authentification
(`dechiffrer_secret` renvoie "" et le login considère la 2FA comme à refaire).

Aucune dépendance nouvelle : `cryptography` est déjà là (python-jose[cryptography]).
"""
import base64
import hashlib
import hmac
import re

from cryptography.fernet import Fernet, InvalidToken  # type: ignore

from app.core.config import get_settings


def _derive(label: str) -> bytes:
    """Clé 32 octets dérivée de COPRO_SECRET_KEY, séparée par usage (label)."""
    secret = get_settings().secret_key
    return hashlib.sha256(f"{secret}:{label}".encode("utf-8")).digest()


def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(_derive("totp")))


def chiffrer_secret(secret: str) -> str:
    """Chiffre le secret TOTP (stocké en base sous forme de jeton opaque)."""
    return _fernet().encrypt(secret.encode("utf-8")).decode("ascii")


def dechiffrer_secret(jeton: str) -> str:
    """Déchiffre un secret TOTP ; renvoie "" si illisible (clé changée, données corrompues)."""
    if not jeton:
        return ""
    try:
        return _fernet().decrypt(jeton.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def normaliser_code_secours(code: str) -> str:
    """Insensible à la casse, espaces et tirets (« abcd-ef234 » → « ABCDEF234 »)."""
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def hacher_code_secours(code: str) -> str:
    """HMAC-SHA256 du code normalisé — les codes ne sont jamais stockés en clair."""
    key = _derive("recovery")
    return hmac.new(key, normaliser_code_secours(code).encode("utf-8"), hashlib.sha256).hexdigest()


def verifier_code_secours(code: str, hash_attendu: str) -> bool:
    return hmac.compare_digest(hacher_code_secours(code), hash_attendu or "")
