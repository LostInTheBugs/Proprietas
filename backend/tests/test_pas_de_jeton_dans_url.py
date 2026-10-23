"""Le jeton de session ne passe JAMAIS par l'URL (`?token=`).

Une URL n'est pas un canal secret : elle est écrite en clair dans les journaux de Caddy,
Traefik, Cloudflare et des proxys, dans l'historique du navigateur, et part dans l'en-tête
Referer. Seuls restent acceptés : l'en-tête `Authorization: Bearer` (API, scripts) et le
cookie de session HttpOnly (navigateur).
"""
from app.core.security import create_access_token, create_scoped_token
from app.core.session import COOKIE_SESSION
from tests.conftest import auth


def test_jeton_en_parametre_d_url_refuse(client, token_a):
    r = client.get(f"/api/auth/me?token={token_a}")
    assert r.status_code == 401, r.text


def test_jeton_2fa_setup_en_parametre_d_url_refuse(client, syndic_a, copro_a):
    tok = create_scoped_token(syndic_a.id, "2fa_setup", copro_id=copro_a.id)
    assert client.post(f"/api/auth/2fa/setup?token={tok}").status_code == 401
    # le même jeton dans l'en-tête reste accepté (étape d'enrôlement forcé)
    assert client.post("/api/auth/2fa/setup", headers=auth(tok)).status_code == 200


def test_migration_de_session_n_accepte_pas_l_url(client, token_a):
    r = client.post(f"/api/auth/session?token={token_a}")
    assert r.status_code == 401
    assert COOKIE_SESSION not in r.cookies


def test_bearer_et_cookie_toujours_acceptes(client, syndic_a, copro_a):
    tok = create_access_token(syndic_a.id, copro_a.id)
    assert client.get("/api/auth/me", headers=auth(tok)).status_code == 200
    client.cookies.set(COOKIE_SESSION, tok)
    assert client.get("/api/auth/me").status_code == 200


def test_parametre_token_absent_de_la_documentation_openapi(client):
    doc = client.get("/openapi.json").json()
    for chemin, operations in doc["paths"].items():
        for op in operations.values():
            noms = [p["name"] for p in op.get("parameters", []) if p.get("in") == "query"]
            assert "token" not in noms, f"?token= encore exposé sur {chemin}"
