"""Session par cookie httpOnly (P3) : pose, priorité Bearer, déconnexion, migration."""
from tests.conftest import auth

PW = "test1234"


def _login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    return r


def test_login_pose_un_cookie_httponly(client, syndic_a):
    client.cookies.clear()
    r = _login(client, "syndic.a@test.fr")
    sc = r.headers.get("set-cookie", "")
    assert "copro_session=" in sc, sc
    assert "HttpOnly" in sc, sc
    assert "samesite=lax" in sc.lower(), sc
    assert "Path=/" in sc, sc


def test_me_par_cookie_seul(client, syndic_a):
    client.cookies.clear()
    _login(client, "syndic.a@test.fr")
    r = client.get("/api/auth/me")  # aucune en-tête : uniquement le cookie du client
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "syndic.a@test.fr"


def test_bearer_prime_sur_le_cookie(client, syndic_a, syndic_b, token_b):
    client.cookies.clear()
    _login(client, "syndic.a@test.fr")  # cookie = A
    r = client.get("/api/auth/me", headers=auth(token_b))  # header = B
    assert r.status_code == 200
    assert r.json()["email"] == "syndic.b@test.fr"


def test_logout_supprime_le_cookie(client, syndic_a):
    client.cookies.clear()
    _login(client, "syndic.a@test.fr")
    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_migration_depuis_bearer(client, syndic_a, token_a):
    client.cookies.clear()
    r = client.post("/api/auth/session", headers=auth(token_a))
    assert r.status_code == 200
    assert "copro_session=" in r.headers.get("set-cookie", "")
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == "syndic.a@test.fr"


def test_cookie_invalide_refuse(client, copro_a):
    client.cookies.clear()
    client.cookies.set("copro_session", "nimportequoi")
    r = client.get("/api/auth/me")
    assert r.status_code == 401
