"""Session par cookie httpOnly (P3) — le navigateur ne stocke plus de jeton.

Le front n'a aucun accès au jeton : il vit dans un cookie `HttpOnly` posé aux
points de connexion (register, login, verify-login 2FA, enrôlement forcé, bascule
de copropriété). Le header `Bearer` et le paramètre `?token=` restent acceptés
(API/CLI, scripts, tests) — le header est PRIORITAIRE sur le cookie.
"""
from fastapi import Request, Response

from app.core.config import get_settings

COOKIE_SESSION = "copro_session"


def requete_https(request: Request) -> bool:
    """La requête est-elle arrivée en HTTPS ? (l'app vit derrière Caddy/Traefik/CF)"""
    proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return proto == "https" or request.url.scheme == "https"


def poser_cookie_session(request: Request, response: Response, token: str) -> None:
    """Pose le cookie de session (durée = durée de vie du jeton)."""
    max_age = get_settings().access_token_expire_minutes * 60
    response.set_cookie(
        COOKIE_SESSION,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=requete_https(request),
        path="/",
    )


def supprimer_cookie_session(response: Response) -> None:
    response.delete_cookie(COOKIE_SESSION, path="/")


def jeton_entrant(request: Request) -> str:
    """Jeton porté par la requête, par ordre de priorité : Bearer > ?token= > cookie."""
    h = request.headers.get("authorization") or ""
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    return request.query_params.get("token") or request.cookies.get(COOKIE_SESSION) or ""
