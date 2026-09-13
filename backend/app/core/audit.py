"""Journal d'audit — traces des actions sensibles.

Utilisation type dans une route :

    audit.enregistrer(db, "relance_envoyee", user=user, copro_id=copro.id,
                      detail="Lot 3", request=request)
    db.commit()   # l'entrée est écrite avec la transaction de la route

`enregistrer` ne lève JAMAIS d'exception : le journal ne doit pas casser une
action métier (une entrée manquée est logguée, pas propagée).
"""
import logging

from app.models.audit import AuditLog

log = logging.getLogger("uvicorn.error")


def client_ip(request) -> str:
    """IP réelle du client : Cloudflare (CF-Connecting-IP), puis proxy (XFF), puis direct."""
    if request is None:
        return ""
    ip = (request.headers.get("cf-connecting-ip") or "").strip()
    if ip:
        return ip
    xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if xff:
        return xff
    return request.client.host if request.client else ""


def enregistrer(db, action: str, user=None, copro_id: int | None = None,
                detail: str = "", request=None) -> None:
    """Ajoute une entrée d'audit à la session courante (commit par l'appelant)."""
    try:
        db.add(AuditLog(
            action=action,
            user_id=user.id if user else None,
            user_email=(getattr(user, "email", "") if user else "") or "",
            user_nom=(getattr(user, "nom", "") if user else "") or "",
            copro_id=copro_id,
            detail=(detail or "")[:500],
            ip=client_ip(request)[:64],
            user_agent=((request.headers.get("user-agent") if request else "") or "")[:250],
        ))
    except Exception as e:  # pragma: no cover — jamais bloquant
        log.warning("audit: entrée non enregistrée (%s) : %s", action, e)
