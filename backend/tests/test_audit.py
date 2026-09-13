"""Journal d'audit : traçage des connexions et actions sensibles + droits d'accès."""
from tests.conftest import _make_membre, auth
from app.core.security import create_access_token


def _entrees(client, token):
    r = client.get("/api/audit", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def test_journal_trace_connexions(client, db, copro_a, syndic_a):
    # Échec puis succès → les deux événements sont journalisés
    client.post("/api/auth/login", json={"email": "syndic.a@test.fr", "password": "mauvais"})
    r = client.post("/api/auth/login", json={"email": "syndic.a@test.fr", "password": "test1234"})
    assert r.status_code == 200, r.text

    entrees = _entrees(client, create_access_token(syndic_a.id, copro_a.id))
    actions = [e["action"] for e in entrees]
    assert "login_failed" in actions and "login" in actions
    # Le plus récent d'abord
    assert actions[0] == "login"
    login = next(e for e in entrees if e["action"] == "login")
    assert login["user_email"] == "syndic.a@test.fr"
    assert login["ip"]  # renseignée (TestClient)
    assert login["created_at"]


def test_journal_reserve_au_syndic(client, db, copro_a):
    membre = _make_membre(db, "membre.a@test.fr", copro_a)
    r = client.get("/api/audit", headers=auth(create_access_token(membre.id, copro_a.id)))
    assert r.status_code == 403


def test_journal_isolation_multicopro(client, db, copro_a, copro_b, syndic_a, syndic_b):
    client.post("/api/auth/login", json={"email": "syndic.a@test.fr", "password": "test1234"})
    entrees_b = _entrees(client, create_access_token(syndic_b.id, copro_b.id))
    assert all(e["user_email"] != "syndic.a@test.fr" for e in entrees_b)


def test_journal_trace_export(client, db, copro_a, syndic_a):
    tok = create_access_token(syndic_a.id, copro_a.id)
    r = client.get("/api/export/compte-gestion", headers=auth(tok))
    assert r.status_code == 200
    entrees = _entrees(client, tok)
    export = next((e for e in entrees if e["action"] == "export_csv"), None)
    assert export is not None
    assert export["user_email"] == "syndic.a@test.fr"


def test_journal_pagination_et_filtre(client, db, copro_a, syndic_a):
    tok = create_access_token(syndic_a.id, copro_a.id)
    for _ in range(3):
        client.post("/api/auth/login", json={"email": "syndic.a@test.fr", "password": "test1234"})
    r = client.get("/api/audit?action=login&limit=2", headers=auth(tok))
    assert r.status_code == 200
    assert len(r.json()) == 2
    r = client.get("/api/audit?offset=1&limit=1&action=login", headers=auth(tok))
    assert r.status_code == 200 and len(r.json()) == 1


def test_journal_inclut_entrees_sans_copro_du_compte(client, db, copro_a, copro_b, syndic_a, syndic_b):
    """Une entrée sans copro (ex. premier enrôlement 2FA) d'un compte de la copro
    reste visible dans le journal de cette copro — mais pas dans celui d'une autre."""
    from app.models.audit import AuditLog

    membre = _make_membre(db, "membre.a@test.fr", copro_a)
    db.add(AuditLog(action="2fa_enabled", user_id=membre.id, user_email=membre.email,
                    user_nom=membre.nom, copro_id=None))
    db.commit()

    entrees_a = _entrees(client, create_access_token(syndic_a.id, copro_a.id))
    assert any(e["action"] == "2fa_enabled" and e["user_email"] == "membre.a@test.fr"
               for e in entrees_a)
    entrees_b = _entrees(client, create_access_token(syndic_b.id, copro_b.id))
    assert all(e["user_email"] != "membre.a@test.fr" for e in entrees_b)
