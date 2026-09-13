"""Révocation de sessions (« déconnecter tous mes appareils ») + compatibilité."""
from datetime import datetime, timedelta, timezone

from jose import jwt

from app.core.config import get_settings
from app.core.security import create_access_token
from tests.conftest import auth


def test_logout_all_revoque_tous_les_jetons(client, db, copro_a, syndic_a):
    tok1 = create_access_token(syndic_a.id, copro_a.id, ver=0)
    tok2 = create_access_token(syndic_a.id, copro_a.id, ver=0)
    assert client.get("/api/auth/me", headers=auth(tok1)).status_code == 200
    assert client.get("/api/auth/me", headers=auth(tok2)).status_code == 200

    r = client.post("/api/auth/logout-all", headers=auth(tok1))
    assert r.status_code == 200, r.text

    # Les DEUX jetons sont morts
    assert client.get("/api/auth/me", headers=auth(tok1)).status_code == 401
    assert client.get("/api/auth/me", headers=auth(tok2)).status_code == 401

    # Reconnexion : nouveau jeton valide (version à jour)
    d = client.post("/api/auth/login",
                    json={"email": "syndic.a@test.fr", "password": "test1234"}).json()
    assert d.get("access_token")
    assert client.get("/api/auth/me", headers=auth(d["access_token"])).status_code == 200

    # Journal d'audit : l'événement est tracé
    entrees = client.get("/api/audit?limit=20", headers=auth(d["access_token"])).json()
    assert any(e["action"] == "sessions_revoked" for e in entrees)


def test_jetons_anciens_sans_version_toujours_valides(client, db, copro_a, syndic_a):
    """Compatibilité de mise à jour : un jeton émis AVANT (sans claim « ver »)
    reste valide tant que le compte n'a jamais révoqué ses sessions."""
    settings = get_settings()
    payload = {"sub": str(syndic_a.id),
               "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    ancien = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    assert client.get("/api/auth/me", headers=auth(ancien)).status_code == 200


def test_scoped_token_refuse_apres_revocation(client, db, copro_a, syndic_a):
    """Un jeton à portée (2FA) émis avant la révocation est refusé aussi."""
    from app.core.security import create_scoped_token
    scoped = create_scoped_token(syndic_a.id, "2fa_challenge", ver=0)
    assert client.post("/api/auth/logout-all",
                       headers=auth(create_access_token(syndic_a.id, copro_a.id, ver=0))).status_code == 200
    r = client.post("/api/auth/2fa/verify-login",
                    json={"challenge_token": scoped, "code": "12345"})
    assert r.status_code == 401
