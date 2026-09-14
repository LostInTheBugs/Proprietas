"""Comptes utilisateurs — édition des fiches et lien « Lots & occupants ».

Réglages → Comptes utilisateurs : le syndic modifie l'email, le prénom, le nom,
le rôle et le mot de passe d'un compte de SA copropriété, et peut lier un compte
à une fiche personne (un compte par personne au maximum).
"""
from sqlalchemy import text

from tests.conftest import auth, _make_membre
from app.core import rate_limit
from app.core.security import create_access_token
from app.models.personne import Personne


def _personne(db, copro, nom="Durand", prenom="Paul", email="paul@test.fr"):
    p = Personne(copropriete_id=copro.id, nom=nom, prenom=prenom, email=email)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _payload(**kwargs):
    base = {"email": "membre.a@test.fr", "nom": "Membre", "prenom": "Alice",
            "role": "membre", "personne_id": None}
    base.update(kwargs)
    return base


def test_update_user_champs_ok(client, db, copro_a, syndic_a, token_a):
    """Édition complète : email, prénom, nom et rôle — la connexion suit."""
    membre = _make_membre(db, "membre.a@test.fr", copro_a)
    r = client.put(f"/api/auth/users/{membre.id}", headers=auth(token_a), json=_payload(
        email="Nouveau@test.fr", nom="Martin", prenom="Claire", role="syndic"))
    assert r.status_code == 200, r.text
    data = r.json()
    assert (data["email"], data["nom"], data["prenom"], data["role"]) == \
        ("nouveau@test.fr", "Martin", "Claire", "syndic")

    # Le nouvel email sert à se connecter ; l'ancien ne vaut plus rien
    assert client.post("/api/auth/login", json={"email": "nouveau@test.fr",
                                                "password": "test1234"}).status_code == 200
    rate_limit._failures.clear()
    assert client.post("/api/auth/login", json={"email": "membre.a@test.fr",
                                                "password": "test1234"}).status_code == 401

    # Journal d'audit
    r = client.get("/api/audit?action=user_updated", headers=auth(token_a))
    assert r.status_code == 200
    entrees = r.json()
    assert len(entrees) == 1 and "nouveau@test.fr" in entrees[0]["detail"]


def test_update_user_scopes_copro(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a):
    """Un compte d'une autre copropriété est invisible (404), comme un id inconnu."""
    assert client.put(f"/api/auth/users/{syndic_b.id}", headers=auth(token_a),
                      json=_payload(email="syndic.b@test.fr")).status_code == 404
    assert client.put("/api/auth/users/99999", headers=auth(token_a),
                      json=_payload()).status_code == 404


def test_update_propre_role_interdit(client, copro_a, syndic_a, token_a):
    """On ne peut pas changer son propre rôle (verrouillage hors administration),
    mais on peut modifier ses propres prénom / nom / email."""
    r = client.put(f"/api/auth/users/{syndic_a.id}", headers=auth(token_a),
                   json=_payload(email="syndic.a@test.fr", role="membre"))
    assert r.status_code == 400
    assert "propre rôle" in r.text

    r = client.put(f"/api/auth/users/{syndic_a.id}", headers=auth(token_a),
                   json=_payload(email="chef@test.fr", nom="Syndic", prenom="Sacha", role="syndic"))
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "chef@test.fr"
    assert r.json()["prenom"] == "Sacha"


def test_update_email_duplique(client, db, copro_a, syndic_a, token_a):
    membre = _make_membre(db, "membre.a@test.fr", copro_a)
    # Casse et espaces ignorés : le contrôle d'unicité reste global
    r = client.put(f"/api/auth/users/{membre.id}", headers=auth(token_a),
                   json=_payload(email="  SYNDIC.A@TEST.FR "))
    assert r.status_code == 400
    assert "déjà utilisé" in r.text


def test_update_role_invalide_422(client, db, copro_a, syndic_a, token_a):
    membre = _make_membre(db, "membre.a@test.fr", copro_a)
    assert client.put(f"/api/auth/users/{membre.id}", headers=auth(token_a),
                      json=_payload(role="admin")).status_code == 422


def test_update_mot_de_passe(client, db, copro_a, syndic_a, token_a):
    membre = _make_membre(db, "membre.a@test.fr", copro_a)
    # Champ vide = mot de passe conservé
    r = client.put(f"/api/auth/users/{membre.id}", headers=auth(token_a),
                   json=_payload(email="membre.a@test.fr", password=""))
    assert r.status_code == 200, r.text
    assert client.post("/api/auth/login", json={"email": "membre.a@test.fr",
                                                "password": "test1234"}).status_code == 200
    # Nouveau mot de passe : l'ancien ne fonctionne plus
    r = client.put(f"/api/auth/users/{membre.id}", headers=auth(token_a),
                   json=_payload(email="membre.a@test.fr", password="nouveau123"))
    assert r.status_code == 200, r.text
    rate_limit._failures.clear()
    assert client.post("/api/auth/login", json={"email": "membre.a@test.fr",
                                                "password": "test1234"}).status_code == 401
    rate_limit._failures.clear()
    assert client.post("/api/auth/login", json={"email": "membre.a@test.fr",
                                                "password": "nouveau123"}).status_code == 200
    # Trop court → refusé (422)
    assert client.put(f"/api/auth/users/{membre.id}", headers=auth(token_a),
                      json=_payload(email="membre.a@test.fr", password="abc")).status_code == 422


def test_edition_reservee_au_syndic(client, db, copro_a, syndic_a):
    membre = _make_membre(db, "membre.a@test.fr", copro_a)
    token_membre = create_access_token(membre.id, copro_a.id)
    assert client.put(f"/api/auth/users/{membre.id}", headers=auth(token_membre),
                      json=_payload(email="membre.a@test.fr")).status_code == 403


def test_lien_personne_creation_edition(client, db, copro_a, syndic_a, token_a):
    """Lien compte ↔ fiche personne : posé à la création, retiré à l'édition."""
    p = _personne(db, copro_a)
    r = client.post("/api/auth/users", headers=auth(token_a), json={
        "email": "paul@test.fr", "password": "test1234", "nom": "Durand",
        "prenom": "Paul", "role": "membre", "personne_id": p.id})
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    assert r.json()["personne_id"] == p.id

    # Badge « compte » côté Lots & occupants
    rp = client.get("/api/personnes", headers=auth(token_a))
    assert rp.status_code == 200
    item = next(x for x in rp.json() if x["id"] == p.id)
    assert item["a_un_compte"] is True

    # Retrait du lien (personne_id null)
    r = client.put(f"/api/auth/users/{uid}", headers=auth(token_a),
                   json=_payload(email="paul@test.fr", nom="Durand", prenom="Paul"))
    assert r.status_code == 200, r.text
    assert r.json()["personne_id"] is None
    rp = client.get("/api/personnes", headers=auth(token_a))
    assert next(x for x in rp.json() if x["id"] == p.id)["a_un_compte"] is False


def test_personne_liee_autre_copro_404(client, db, copro_a, copro_b, syndic_a, token_a):
    p_b = _personne(db, copro_b, nom="Autre")
    r = client.post("/api/auth/users", headers=auth(token_a), json={
        "email": "paul@test.fr", "password": "test1234", "nom": "Durand",
        "prenom": "Paul", "role": "membre", "personne_id": p_b.id})
    assert r.status_code == 404

    membre = _make_membre(db, "membre.a@test.fr", copro_a)
    r = client.put(f"/api/auth/users/{membre.id}", headers=auth(token_a),
                   json=_payload(email="membre.a@test.fr", personne_id=p_b.id))
    assert r.status_code == 404


def test_personne_deja_liee_400(client, db, copro_a, syndic_a, token_a):
    p = _personne(db, copro_a)
    membre = _make_membre(db, "membre.a@test.fr", copro_a)
    assert client.put(f"/api/auth/users/{membre.id}", headers=auth(token_a),
                      json=_payload(email="membre.a@test.fr", personne_id=p.id)).status_code == 200
    # Deuxième compte sur la même fiche → refusé
    r = client.post("/api/auth/users", headers=auth(token_a), json={
        "email": "doublon@test.fr", "password": "test1234", "nom": "Durand",
        "prenom": "Paul", "role": "membre", "personne_id": p.id})
    assert r.status_code == 400
    assert "déjà liée" in r.text
    # Ré-enregistrer le MÊME compte sur la même fiche reste possible
    assert client.put(f"/api/auth/users/{membre.id}", headers=auth(token_a),
                      json=_payload(email="membre.a@test.fr", personne_id=p.id)).status_code == 200


def test_prenom_null_historique_tolere(client, db, copro_a, syndic_a, token_a):
    """Colonne ajoutée par ALTER TABLE : NULL sur les lignes existantes → lisible.

    Régression classique (ResponseValidationError → 500) : on injecte NULL par
    SQL brut + expire_all (l'identity map masquerait le bug).
    """
    db.execute(text("UPDATE users SET prenom = NULL WHERE id = :i"), {"i": syndic_a.id})
    db.commit()
    db.expire_all()
    r = client.get("/api/auth/users", headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert next(u for u in r.json() if u["id"] == syndic_a.id)["prenom"] == ""
    r = client.get("/api/auth/me", headers=auth(token_a))
    assert r.status_code == 200 and r.json()["prenom"] == ""


def test_register_avec_prenom(client):
    r = client.post("/api/auth/register", json={
        "email": "premier@test.fr", "password": "test1234", "nom": "Dupont", "prenom": "Marie"})
    assert r.status_code == 200, r.text
    me = client.get("/api/auth/me", headers=auth(r.json()["access_token"]))
    assert me.status_code == 200
    assert me.json()["prenom"] == "Marie" and me.json()["nom"] == "Dupont"
