"""Administrateurs de l'instance gérés dans l'application (plus dans le .env).

- Le premier compte créé (inscription initiale) est administrateur de l'instance.
- Un administrateur en ajoute un autre par son e-mail, ou en retire un.
- Garde-fous : jamais le compte de démonstration ; on ne se retire pas soi-même
  (il reste donc toujours au moins un administrateur).
- Mode bureau : le syndic local reste administrateur, sans case à cocher.
"""
import pytest

from app.core.config import get_settings
from app.core.deps import is_instance_admin
from app.core.security import hash_password
from app.models.user import User
from tests.conftest import auth


@pytest.fixture(autouse=True)
def _serveur(monkeypatch):
    monkeypatch.setattr(get_settings(), "update_mode", "server")


@pytest.fixture()
def admin_a(db, syndic_a):
    syndic_a.is_instance_admin = True
    db.commit()
    return syndic_a


def test_premier_compte_inscrit_est_admin_d_instance(client, db):
    r = client.post("/api/auth/register", json={
        "email": "fondateur@test.fr", "password": "motdepasse-solide-123", "prenom": "Fred", "nom": "F"})
    assert r.status_code == 200, r.text
    u = db.query(User).filter(User.email == "fondateur@test.fr").one()
    assert u.is_instance_admin is True


def test_syndic_ordinaire_n_est_pas_admin(syndic_b):
    assert is_instance_admin(syndic_b) is False


def test_le_compte_demo_n_est_jamais_admin(db, syndic_b):
    syndic_b.is_instance_admin, syndic_b.is_demo = True, True
    db.commit()
    assert is_instance_admin(syndic_b) is False


def test_liste_ajout_retrait(client, db, admin_a, token_a, syndic_b):
    h = auth(token_a)
    emails = lambda: [a["email"] for a in client.get("/api/admin/instance-admins", headers=h).json()]
    assert emails() == ["syndic.a@test.fr"]
    r = client.post("/api/admin/instance-admins", json={"email": "  SYNDIC.B@test.fr "}, headers=h)
    assert r.status_code == 200, r.text
    assert sorted(emails()) == ["syndic.a@test.fr", "syndic.b@test.fr"]
    r = client.delete(f"/api/admin/instance-admins/{syndic_b.id}", headers=h)
    assert r.status_code == 200, r.text
    assert emails() == ["syndic.a@test.fr"]


def test_ajout_compte_inconnu_404(client, admin_a, token_a):
    r = client.post("/api/admin/instance-admins", json={"email": "personne@test.fr"}, headers=auth(token_a))
    assert r.status_code == 404
    # Le message prouve que c'est la route qui répond, pas un 404 de route inexistante.
    assert "Aucun compte" in r.json()["detail"]


def test_ajout_compte_demo_refuse(client, db, admin_a, token_a):
    demo = User(email="demo@test.fr", password_hash=hash_password("x"), nom="Démo", is_demo=True)
    db.add(demo)
    db.commit()
    r = client.post("/api/admin/instance-admins", json={"email": "demo@test.fr"}, headers=auth(token_a))
    assert r.status_code == 400
    assert "démonstration" in r.json()["detail"]


def test_on_ne_se_retire_pas_soi_meme(client, admin_a, token_a):
    r = client.delete(f"/api/admin/instance-admins/{admin_a.id}", headers=auth(token_a))
    assert r.status_code == 400
    assert "vous-même" in r.json()["detail"]


def test_reserve_aux_admins(client, admin_a, token_b, syndic_b):
    h = auth(token_b)
    assert client.get("/api/admin/instance-admins", headers=h).status_code == 403
    r = client.post("/api/admin/instance-admins", json={"email": "syndic.b@test.fr"}, headers=h)
    assert r.status_code == 403


def test_ajout_et_retrait_traces_dans_l_audit(client, db, admin_a, token_a, syndic_b):
    from app.models.audit import AuditLog
    h = auth(token_a)
    client.post("/api/admin/instance-admins", json={"email": "syndic.b@test.fr"}, headers=h)
    client.delete(f"/api/admin/instance-admins/{syndic_b.id}", headers=h)
    actions = [a.action for a in db.query(AuditLog).order_by(AuditLog.id).all()]
    assert "instance_admin_added" in actions and "instance_admin_removed" in actions


def test_bureau_le_syndic_local_est_admin_sans_case(monkeypatch, syndic_b):
    monkeypatch.setattr(get_settings(), "update_mode", "desktop")
    assert is_instance_admin(syndic_b) is True
