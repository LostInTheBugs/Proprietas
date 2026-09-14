"""Comptes utilisateurs — édition des fiches, auto-édition et suppression.

Réglages → Comptes utilisateurs : le syndic modifie l'email, le prénom, le nom,
le rôle, l'adresse et le téléphone d'un compte de SA copropriété. Chacun peut
aussi modifier SES PROPRES coordonnées (Réglages → Mes informations, PUT /auth/me).

Modèle « zéro fiche » : les comptes utilisateurs SONT les personnes — les fiches
« Lots & occupants » n'existent plus.
"""
from datetime import datetime

from sqlalchemy import text

from tests.conftest import auth, _make_membre
from app.core import rate_limit
from app.core.security import create_access_token
from app.models.lot import Lot
from app.models.invitation import Invitation
from app.models.relance import Relance
from app.models.recouvrement import ActeRecouvrement
from app.models.user import User


def _payload(**kwargs):
    base = {"email": "membre.a@test.fr", "nom": "Membre", "prenom": "Alice",
            "role": "membre", "adresse": "", "telephone": ""}
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


def test_update_user_coordonnees(client, db, copro_a, syndic_a, token_a):
    """Adresse et téléphone modifiables par le syndic (traçés dans l'audit)."""
    membre = _make_membre(db, "membre.a@test.fr", copro_a)
    r = client.put(f"/api/auth/users/{membre.id}", headers=auth(token_a), json=_payload(
        adresse="9 rue de la Roquette, 75011 Paris", telephone="06 12 34 56 78"))
    assert r.status_code == 200, r.text
    assert r.json()["adresse"] == "9 rue de la Roquette, 75011 Paris"
    assert r.json()["telephone"] == "06 12 34 56 78"
    r = client.get("/api/audit?action=user_updated", headers=auth(token_a))
    detail = r.json()[0]["detail"]
    assert "adresse" in detail and "téléphone" in detail


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


# ---------- Auto-édition (Réglages → Mes informations) ----------
def test_profil_auto_edition(client, db, copro_a, syndic_a):
    """Un copropriétaire modifie SES coordonnées (pas le rôle, pas les autres)."""
    membre = _make_membre(db, "membre.a@test.fr", copro_a)
    token = create_access_token(membre.id, copro_a.id)
    r = client.put("/api/auth/me", headers=auth(token), json={
        "prenom": "Alice", "nom": "Martin", "email": "alice.martin@test.fr",
        "adresse": "2 rue du Test, 75011 Paris", "telephone": "06 98 76 54 32"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["email"] == "alice.martin@test.fr"
    assert data["adresse"] == "2 rue du Test, 75011 Paris"
    assert data["telephone"] == "06 98 76 54 32"
    assert data["role"] == "membre"  # le rôle n'est jamais modifiable ici

    # Le nouvel email sert à se connecter
    assert client.post("/api/auth/login", json={"email": "alice.martin@test.fr",
                                                "password": "test1234"}).status_code == 200

    # Audit « profil_updated »
    r = client.get("/api/audit?action=profil_updated", headers=auth(create_access_token(syndic_a.id, copro_a.id)))
    assert r.status_code == 200
    entrees = r.json()
    assert len(entrees) == 1
    assert "adresse" in entrees[0]["detail"] and "téléphone" in entrees[0]["detail"]


def test_profil_auto_edition_email_duplique(client, db, copro_a, syndic_a):
    membre = _make_membre(db, "membre.a@test.fr", copro_a)
    token = create_access_token(membre.id, copro_a.id)
    r = client.put("/api/auth/me", headers=auth(token), json={
        "prenom": "Alice", "nom": "Martin", "email": "syndic.a@test.fr",
        "adresse": "", "telephone": ""})
    assert r.status_code == 400
    assert "déjà utilisé" in r.text


def test_profil_auto_edition_nom_requis(client, db, copro_a, syndic_a):
    membre = _make_membre(db, "membre.a@test.fr", copro_a)
    token = create_access_token(membre.id, copro_a.id)
    r = client.put("/api/auth/me", headers=auth(token), json={
        "prenom": "Alice", "nom": "  ", "email": "membre.a@test.fr",
        "adresse": "", "telephone": ""})
    assert r.status_code == 422


def test_prenom_null_historique_tolere(client, db, copro_a, syndic_a, token_a):
    """Colonnes ajoutées par ALTER TABLE : NULL sur les lignes existantes → lisible.

    Régression classique (ResponseValidationError → 500) : on injecte NULL par
    SQL brut + expire_all (l'identity map masquerait le bug).
    """
    db.execute(text("UPDATE users SET prenom = NULL, adresse = NULL, telephone = NULL WHERE id = :i"),
               {"i": syndic_a.id})
    db.commit()
    db.expire_all()
    r = client.get("/api/auth/users", headers=auth(token_a))
    assert r.status_code == 200, r.text
    u = next(x for x in r.json() if x["id"] == syndic_a.id)
    assert u["prenom"] == "" and u["adresse"] == "" and u["telephone"] == ""
    r = client.get("/api/auth/me", headers=auth(token_a))
    assert r.status_code == 200 and r.json()["prenom"] == ""
    assert r.json()["adresse"] == "" and r.json()["telephone"] == ""


def test_register_avec_prenom(client):
    r = client.post("/api/auth/register", json={
        "email": "premier@test.fr", "password": "test1234", "nom": "Dupont", "prenom": "Marie"})
    assert r.status_code == 200, r.text
    me = client.get("/api/auth/me", headers=auth(r.json()["access_token"]))
    assert me.status_code == 200
    assert me.json()["prenom"] == "Marie" and me.json()["nom"] == "Dupont"


# ---------- Suppression ----------
def _lot(db, copro, numero="1", tantiemes=1000, proprietaire_id=None):
    lot = Lot(copropriete_id=copro.id, numero=numero, tantiemes=tantiemes,
              proprietaire_id=proprietaire_id)
    db.add(lot)
    db.commit()
    db.refresh(lot)
    return lot


def test_delete_user_conserve_actes_recouvrement(client, db, copro_a, syndic_a, token_a):
    """Supprimer un compte ne supprime pas ses actes de recouvrement (lien délié).

    Sans le déliage, la suppression échoue en base (FK actes_recouvrement.created_by_id).
    """
    membre = _make_membre(db, "membre.a@test.fr", copro_a)
    lot = _lot(db, copro_a)
    acte = ActeRecouvrement(copropriete_id=copro_a.id, lot_id=lot.id, type="note",
                            libelle="Frais test", created_by_id=membre.id)
    db.add(acte)
    db.commit()
    db.refresh(acte)

    assert client.delete(f"/api/auth/users/{membre.id}", headers=auth(token_a)).status_code == 200
    db.expire_all()
    reste = db.query(ActeRecouvrement).filter(ActeRecouvrement.id == acte.id).first()
    assert reste is not None, "l'acte doit survivre à la suppression du compte"
    assert reste.created_by_id is None


def test_delete_user_delie_lots_relances_convocations(client, db, copro_a, syndic_a, token_a):
    """Suppression d'un compte propriétaire : l'historique survit, délié (RGPD).

    Le lot repasse « sans propriétaire », les relances/convocations reçues
    restent attachées au lot / à l'AG — seule la personne est supprimée.
    """
    from app.models.ag import AG
    membre = _make_membre(db, "membre.a@test.fr", copro_a)
    lot = _lot(db, copro_a, proprietaire_id=membre.id)
    ag = AG(copropriete_id=copro_a.id, date=datetime(2026, 10, 1), statut="projet")
    db.add(ag)
    db.commit()
    db.refresh(ag)
    relance = Relance(lot_id=lot.id, personne_id=membre.id, date_envoi=datetime(2026, 1, 5),
                      statut="envoye", montant_du=120.0)
    invitation = Invitation(ag_id=ag.id, personne_id=membre.id,
                            date_envoi=datetime(2026, 1, 6), statut="envoye")
    acte = ActeRecouvrement(copropriete_id=copro_a.id, lot_id=lot.id, type="note",
                            personne_id=membre.id)
    db.add(relance)
    db.add(invitation)
    db.add(acte)
    db.commit()
    for obj in (relance, invitation, acte):
        db.refresh(obj)

    membre_id = membre.id  # capturé avant suppression (l'instance expire ensuite)
    assert client.delete(f"/api/auth/users/{membre_id}", headers=auth(token_a)).status_code == 200
    db.expire_all()
    lot_apres = db.query(Lot).filter(Lot.id == lot.id).first()
    assert lot_apres is not None and lot_apres.proprietaire_id is None
    for obj, champ in ((relance, "personne_id"), (invitation, "personne_id"), (acte, "personne_id")):
        reste = db.query(type(obj)).filter(type(obj).id == obj.id).first()
        assert reste is not None, f"{type(obj).__name__} doit survivre"
        assert getattr(reste, champ) is None
    assert db.query(User).filter(User.id == membre_id).count() == 0
