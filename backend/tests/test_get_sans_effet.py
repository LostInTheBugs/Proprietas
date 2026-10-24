"""Un GET ne crée pas de copropriété pour un copropriétaire sans liaison.

Un GET est une méthode « sûre » (HTTP) : préchargement du navigateur, robot, nouvelle
tentative réseau ou balise <img> peuvent le déclencher. Avant, un compte « membre » sans
liaison se voyait créer une copropriété vide à son nom à la première lecture : données
fantômes, et un simple copropriétaire devenu seul occupant d'un immeuble vide.
Seul le syndic garde l'initialisation au premier accès (installation neuve).
"""
from app.core.security import create_access_token, hash_password
from app.models.copropriete import Copropriete
from app.models.user import User, UserCopro
from tests.conftest import auth


def _compte(db, role):
    u = User(email=f"{role}.seul@test.fr", password_hash=hash_password("x"), nom="Seul", role=role)
    db.add(u)
    db.commit()
    return u


def test_membre_sans_liaison_404_et_rien_de_cree(client, db):
    u = _compte(db, "membre")
    avant = db.query(Copropriete).count()
    for chemin in ("/api/copro", "/api/copro/tresorerie", "/api/lots"):
        r = client.get(chemin, headers=auth(create_access_token(u.id)))
        assert r.status_code == 404, (chemin, r.text)
        assert r.json()["detail"] == "Aucune copropriété associée à ce compte"
    assert db.query(Copropriete).count() == avant
    assert db.query(UserCopro).filter(UserCopro.user_id == u.id).count() == 0


def test_syndic_sans_liaison_initialise_sa_copropriete(client, db):
    u = _compte(db, "syndic")
    r = client.get("/api/copro", headers=auth(create_access_token(u.id)))
    assert r.status_code == 200, r.text
    assert db.query(UserCopro).filter(UserCopro.user_id == u.id).count() == 1
    # deuxième lecture : la même copropriété, rien de plus
    avant = db.query(Copropriete).count()
    assert client.get("/api/copro", headers=auth(create_access_token(u.id))).json()["id"] == r.json()["id"]
    assert db.query(Copropriete).count() == avant


def test_inscription_puis_premier_acces_inchange(client):
    r = client.post("/api/auth/register", json={
        "email": "premier@test.fr", "password": "motdepasse-solide-123", "nom": "Premier"})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]     # 2FA par défaut désactivée dans les tests (conftest)
    assert client.get("/api/copro", headers=auth(tok)).status_code == 200
