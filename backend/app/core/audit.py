"""Journal d'audit — traces des actions sensibles.

Utilisation type dans une route :

    audit.enregistrer(db, "relance_envoyee", user=user, copro_id=copro.id,
                      detail="Lot 3", request=request)
    db.commit()   # l'entrée est écrite avec la transaction de la route

`enregistrer` ne lève JAMAIS d'exception : le journal ne doit pas casser une
action métier (une entrée manquée est logguée, pas propagée).
"""
import ipaddress
import logging

from app.models.audit import AuditLog

log = logging.getLogger("uvicorn.error")


# Plages d'adresses de Cloudflare (https://www.cloudflare.com/ips-v4 et ips-v6, relevées le 20/11/2026).
CLOUDFLARE = tuple(ipaddress.ip_network(p) for p in (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22", "141.101.64.0/18",
    "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20", "197.234.240.0/22", "198.41.128.0/17",
    "162.158.0.0/15", "104.16.0.0/13", "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
    "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32", "2405:8100::/32",
    "2a06:98c0::/29", "2c0f:f248::/32"))


def _ip(texte: str):
    try:
        return ipaddress.ip_address((texte or "").strip())
    except ValueError:
        return None


def client_ip(request) -> str:
    """IP réelle du client, sans croire un en-tête que le client a pu écrire lui-même (audit, limitation des
    tentatives de connexion).

    1. Le serveur ne voit en direct que son voisin : `request.client.host`.
    2. Voisin sur un réseau privé (le proxy Caddy du docker compose) : l'adresse qui s'est connectée au proxy
       est la DERNIÈRE de X-Forwarded-For (Caddy y met ou y ajoute l'adresse de son voisin ; les valeurs
       précédentes viennent du client). Voisin public (application exposée sans proxy) : on l'en croit lui seul.
    3. Si cette adresse est celle de Cloudflare, CF-Connecting-IP donne le vrai client ; sinon cet en-tête est
       ignoré : quelqu'un qui contourne Cloudflare ne choisit plus l'adresse inscrite.
    """
    if request is None:
        return ""
    voisin = request.client.host if request.client else ""
    v = _ip(voisin)
    saut = voisin
    if v is None or v.is_private or v.is_loopback:      # None : socket Unix d'un proxy local (ou client de test)
        xff = [x.strip() for x in (request.headers.get("x-forwarded-for") or "").split(",") if x.strip()]
        if xff and _ip(xff[-1]) is not None:
            saut = xff[-1]
    s = _ip(saut)
    if s is not None and any(s in plage for plage in CLOUDFLARE if s.version == plage.version):
        cf = (request.headers.get("cf-connecting-ip") or "").strip()
        if _ip(cf) is not None:
            return cf
    return saut


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
