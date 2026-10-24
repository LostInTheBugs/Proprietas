"""Chiffrement des secrets (2FA, mot de passe SMTP) et hachage des codes de secours.

La clé de chiffrement (Fernet) et la clé de hachage sont DÉRIVÉES de
COPRO_SECRET_KEY : si cette clé change, les secrets TOTP existants deviennent
illisibles — les comptes doivent ré-enrôler leur double authentification
(`dechiffrer_secret` renvoie "" et le login considère la 2FA comme à refaire).

Dépendance : `cryptography`, épinglée explicitement dans requirements.txt.
"""
import base64
import hashlib
import hmac
import re

from cryptography.fernet import Fernet, InvalidToken  # type: ignore
from sqlalchemy import String, text
from sqlalchemy.types import TypeDecorator

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


# ---------------------------------------------------------------- textes chiffrés en base
# Mot de passe SMTP (RGPD art. 32) : stocké « enc:v1:<jeton Fernet> », clé dérivée de
# COPRO_SECRET_KEY (label « smtp », distincte de celle du TOTP). Une valeur SANS préfixe est un
# ancien mot de passe en clair : lu tel quel, rechiffré au démarrage (rechiffrer_secrets_smtp).
PREFIXE_CHIFFRE = "enc:v1:"


def chiffrer_texte(texte: str, label: str = "smtp") -> str:
    if not texte or texte.startswith(PREFIXE_CHIFFRE):
        return texte or ""
    jeton = Fernet(base64.urlsafe_b64encode(_derive(label))).encrypt(texte.encode("utf-8"))
    return PREFIXE_CHIFFRE + jeton.decode("ascii")


def dechiffrer_texte(valeur: str, label: str = "smtp") -> str:
    """Texte en clair ; "" si illisible (COPRO_SECRET_KEY changée : à ressaisir)."""
    if not valeur:
        return ""
    if not valeur.startswith(PREFIXE_CHIFFRE):
        return valeur                       # ancien stockage en clair
    try:
        jeton = valeur[len(PREFIXE_CHIFFRE):].encode("ascii")
        return Fernet(base64.urlsafe_b64encode(_derive(label))).decrypt(jeton).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


class TexteChiffre(TypeDecorator):
    """Colonne texte chiffrée de façon transparente : le code lit et écrit du clair."""
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return chiffrer_texte(value) if value else value

    def process_result_value(self, value, dialect):
        return dechiffrer_texte(value) if value else value


def rechiffrer_secrets_smtp(db) -> int:
    """Chiffre les mots de passe SMTP encore stockés en clair (appelé au démarrage)."""
    lignes = db.execute(text("SELECT id, smtp_password FROM coproprietes "
                             "WHERE smtp_password IS NOT NULL AND smtp_password <> ''")).all()
    n = 0
    for copro_id, brut in lignes:
        if not brut.startswith(PREFIXE_CHIFFRE):
            db.execute(text("UPDATE coproprietes SET smtp_password = :p WHERE id = :i"),
                       {"p": chiffrer_texte(brut), "i": copro_id})
            n += 1
    db.commit()
    return n


def normaliser_code_secours(code: str) -> str:
    """Insensible à la casse, espaces et tirets (« abcd-ef234 » → « ABCDEF234 »)."""
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def hacher_code_secours(code: str) -> str:
    """HMAC-SHA256 du code normalisé — les codes ne sont jamais stockés en clair."""
    key = _derive("recovery")
    return hmac.new(key, normaliser_code_secours(code).encode("utf-8"), hashlib.sha256).hexdigest()


def verifier_code_secours(code: str, hash_attendu: str) -> bool:
    return hmac.compare_digest(hacher_code_secours(code), hash_attendu or "")
