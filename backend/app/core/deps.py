from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import decode_access_token
from app.core.session import COOKIE_SESSION
from app.models.user import User

security = HTTPBearer(auto_error=False)


def _charger_user(db: Session, raw: str) -> User:
    """Décode le jeton et charge l'utilisateur (payload + portée posés sur l'objet)."""
    payload = decode_access_token(raw)
    if not payload:
        raise HTTPException(401, "Token invalide ou expiré")
    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError):
        raise HTTPException(401, "Token invalide ou expiré")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(401, "Utilisateur introuvable")
    # Révocation globale (« déconnecter tous mes appareils ») : un jeton dont la
    # version ne correspond plus au compte est refusé, même encore valide en date.
    if int(payload.get("ver", 0) or 0) != int(user.token_version or 0):
        raise HTTPException(401, "Session révoquée — reconnectez-vous")
    user._token_data = payload
    user._token_scope = str(payload.get("scope") or "")
    return user


def _raw_token(
    credentials: HTTPAuthorizationCredentials | None, token: str, request: Request | None
) -> str:
    """Jeton entrant par ordre de priorité : Bearer > ?token= > cookie httpOnly.

    L'explicite (header/query) gagne sur le cookie : les scripts, l'API directe et
    les tests restent inchangés, et une requête portant deux identités différentes
    (cas des tests d'isolation) ne peut pas être « détournée » par le cookie.
    """
    if credentials and credentials.credentials:
        return credentials.credentials
    if token:
        return token
    if request is not None:
        return request.cookies.get(COOKIE_SESSION) or ""
    return ""


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    token: str = "",
    request: Request = None,
    db: Session = Depends(get_db),
) -> User:
    """Auth par header Bearer, `?token=` ou cookie de session httpOnly.

    Les jetons à portée (« 2fa_challenge », « 2fa_setup ») sont REFUSÉS ici : ils ne
    servent qu'aux étapes intermédiaires de la double authentification.
    """
    raw = _raw_token(credentials, token, request)
    if not raw:
        raise HTTPException(401, "Authentification requise")
    user = _charger_user(db, raw)
    if user._token_scope:
        raise HTTPException(401, "Double authentification requise")
    return user


def get_current_user_2fa(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    token: str = "",
    request: Request = None,
    db: Session = Depends(get_db),
) -> User:
    """Comme get_current_user, mais accepte AUSSI les jetons d'enrôlement forcé
    (« 2fa_setup ») — utilisé uniquement par les routes setup/verify de la 2FA."""
    raw = _raw_token(credentials, token, request)
    if not raw:
        raise HTTPException(401, "Authentification requise")
    user = _charger_user(db, raw)
    if user._token_scope not in ("", "2fa_setup"):
        raise HTTPException(401, "Jeton à portée insuffisante")
    return user


def require_syndic(user: User = Depends(get_current_user)) -> User:
    if user.role != "syndic":
        raise HTTPException(403, "Réservé au syndic")
    return user


def is_instance_admin(user: User) -> bool:
    """Administrateur de l'INSTANCE (mises à jour) : e-mail listé dans COPRO_INSTANCE_ADMINS
    (serveur), ou le syndic local (version de bureau)."""
    from app.core.config import get_settings
    s = get_settings()
    if s.update_mode == "desktop":
        # Version de bureau : instance mono-poste, le syndic local en est l'administrateur.
        return user.role == "syndic"
    return (user.email or "").strip().lower() in s.instance_admin_emails


def require_instance_admin(user: User = Depends(get_current_user)) -> User:
    if not is_instance_admin(user):
        raise HTTPException(403, "Réservé à l'administrateur de l'instance")
    return user
