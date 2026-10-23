"""Mots de passe (bcrypt) et jetons de session (JWT, PyJWT).

Bibliothèques utilisées en direct : `bcrypt` et `PyJWT` (activement maintenues).
python-jose (peu maintenu, CVE passées) et passlib (abandonné, incompatible avec
bcrypt >= 4.1) ont été retirés en 2026.10. Compatibilité ascendante prouvée par
tests/test_auth_compat.py : les hachages passlib ($2b$) et les jetons python-jose
déjà émis restent valides.
"""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings

settings = get_settings()

# bcrypt ne prend en compte que les 72 premiers octets. passlib tronquait sans erreur :
# on garde exactement ce comportement (sinon des mots de passe longs déjà enregistrés
# deviendraient invalides, et bcrypt >= 5 lève une erreur au-delà de 72 octets).
_BCRYPT_MAX_OCTETS = 72


def _octets(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_OCTETS]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_octets(password), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    """False pour un mauvais mot de passe ET pour un hash illisible en base :
    une connexion refusée (401), jamais une exception (500)."""
    try:
        return bcrypt.checkpw(_octets(plain), (hashed or "").encode("ascii"))
    except ValueError:          # hash absent, tronqué ou d'un autre format
        return False


def create_access_token(user_id: int, copro_id: int | None = None, ver: int = 0) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": str(user_id), "exp": expire, "ver": int(ver or 0)}
    if copro_id:
        payload["copro_id"] = copro_id
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_scoped_token(user_id: int, scope: str, minutes: int = 10,
                        copro_id: int | None = None, ver: int = 0) -> str:
    """Jeton court à PORTÉE LIMITÉE — « 2fa_challenge » (vérification du code de
    connexion) ou « 2fa_setup » (enrôlement forcé). Refusé par toutes les autres
    routes (voir core/deps.py) : il ne remplace jamais un jeton d'accès complet."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload = {"sub": str(user_id), "exp": expire, "scope": scope, "ver": int(ver or 0)}
    if copro_id:
        payload["copro_id"] = copro_id
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str):
    """Charge utile du jeton, ou None s'il est invalide (signature, expiration, format,
    algorithme). `algorithms=[...]` est obligatoire : il interdit « alg: none » et la
    confusion d'algorithmes. Seules les erreurs de jeton sont attrapées (PyJWTError) :
    un bug de programmation reste visible au lieu de passer pour « jeton invalide »."""
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except jwt.PyJWTError:
        return None
