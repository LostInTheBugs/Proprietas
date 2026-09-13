"""Petits utilitaires HTTP : détection HTTPS et requêtes « externes ».

Utilisés par le middleware de détection d'exposition (main.py) et les routes
d'état de l'instance — la détection d'IP réutilise `core.audit.client_ip`.
"""
import ipaddress

from app.core.audit import client_ip


def requete_https(request) -> bool:
    """La requête arrive-t-elle en HTTPS (accès direct ou via proxy TLS) ?"""
    if request is None:
        return False
    if request.url.scheme == "https":
        return True
    xfp = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return xfp == "https"


def est_externe(request) -> bool:
    """La requête vient-elle d'internet (IP publique) ?

    Heuristique : IP publique côté client réel (CF-Connecting-IP / X-Forwarded-For
    / adresse directe). Les IP privées, loopback, réservées et non-parsables
    (TestClient « testclient », UNIX sockets…) sont considérées internes.
    """
    ip = client_ip(request)
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_reserved or addr.is_multicast or addr.is_unspecified
    )
