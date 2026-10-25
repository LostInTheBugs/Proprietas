"""Rate limiting en mémoire (mono-serveur) pour /api/auth/login.

5 tentatives échouées par (email, IP) sur 15 minutes → 429.
Simple et suffisant pour une instance mono-serveur (pas de Redis).
Mémoire bornée : une vérification ne crée aucune entrée, et les entrées expirées sont purgées
(au plus une fois par minute) — sinon des essais avec des identifiants variés feraient grossir
le dictionnaire indéfiniment.
"""
import time
from collections import defaultdict, deque

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 15 * 60

_failures: dict[str, deque[float]] = defaultdict(deque)
PURGE_INTERVAL_SECONDS = 60
_derniere_purge = 0.0


def _purger(now: float) -> None:
    global _derniere_purge
    if now - _derniere_purge < PURGE_INTERVAL_SECONDS:
        return
    _derniere_purge = now
    for cle in [c for c, dq in _failures.items() if not dq or now - dq[-1] > WINDOW_SECONDS]:
        del _failures[cle]


def _key(email: str, ip: str) -> str:
    return f"{email.lower().strip()}|{ip}"


def check_login_allowed(email: str, ip: str) -> None:
    """Lève une exception si le quota de tentatives est dépassé."""
    from fastapi import HTTPException
    now = time.monotonic()
    _purger(now)
    dq = _failures.get(_key(email, ip))   # .get : une simple vérification ne crée pas d'entrée
    if not dq:
        return
    while dq and now - dq[0] > WINDOW_SECONDS:
        dq.popleft()
    if len(dq) >= MAX_ATTEMPTS:
        raise HTTPException(
            429,
            "Trop de tentatives de connexion, réessayez dans quelques minutes",
        )


def record_failure(email: str, ip: str) -> None:
    now = time.monotonic()
    _purger(now)
    _failures[_key(email, ip)].append(now)


def clear_failures(email: str, ip: str) -> None:
    _failures.pop(_key(email, ip), None)
