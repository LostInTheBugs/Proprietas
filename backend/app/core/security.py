from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from jose import jwt
from app.core.config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


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
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except Exception:
        return None
