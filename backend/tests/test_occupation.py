"""Occupation des lots — « propriétaire occupant » dérivé du compte, loué/vacant par lot.

L'occupation ne vit plus sur les fiches personnes : le compte utilisateur lié
déclare « occupe son logement » (→ ses lots s'affichent « propriétaire
occupant »), et chaque lot porte un statut "" | "loue" | "vacant" — jamais de
nom de locataire stocké (RGPD).
"""
from tests.conftest import auth


def _personne(db, copro, nom="Durand", prenom="Paul", email="paul@test.fr"):
    from app.models.personne import Personne
    p = Personne(copropriete_id=copro.id, nom=nom, prenom=prenom, email=email)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _lot(db, copro, numero="1", **kw):
    from app.models.lot import Lot
    lot = Lot(copropriete_id=copro.id, numero=numero, tantiemes=1000, **kw)
    db.add(lot)
    db.commit()
    db.refresh(lot)
    return lot


def test_compte_proprietaire_occupant_roundtrip(client, copro_a, syndic_a, token_a):
    """La case « occupe son logement » se crée et s'édite ; l'audit la trace."""
    r = client.post("/api/auth/users", headers=auth(token_a), json={
        "email": "occ@test.fr", "password": "test1234", "nom": "Durand", "prenom": "Paul",
        "role": "membre", "personne_id": None, "est_occupant": True})
    assert r.status_code == 200, r.text
    assert r.json()["est_occupant"] is True
    uid = r.json()["id"]

    r = client.put(f"/api/auth/users/{uid}", headers=auth(token_a), json={
        "email": "occ@test.fr", "nom": "Durand", "prenom": "Paul", "role": "membre",
        "personne_id": None, "est_occupant": False})
    assert r.status_code == 200, r.text
    assert r.json()["est_occupant"] is False

    entrees = client.get("/api/audit?action=user_updated", headers=auth(token_a)).json()
    assert any("propriétaire occupant" in e["detail"] for e in entrees)


def test_lot_statut_occupation_roundtrip(client, db, copro_a, syndic_a, token_a):
    """Loué / vacant se saisit sur le lot ; toute autre valeur est refusée."""
    p = _personne(db, copro_a)
    r = client.post("/api/lots", headers=auth(token_a), json={
        "numero": "1", "tantiemes": 1000, "proprietaire_id": p.id, "statut_occupation": "loue"})
    assert r.status_code == 200, r.text
    assert r.json()["statut_occupation"] == "loue"
    lot_id = r.json()["id"]

    r = client.put(f"/api/lots/{lot_id}", headers=auth(token_a), json={
        "numero": "1", "tantiemes": 1000, "proprietaire_id": p.id, "statut_occupation": "vacant"})
    assert r.status_code == 200, r.text
    assert r.json()["statut_occupation"] == "vacant"

    r = client.put(f"/api/lots/{lot_id}", headers=auth(token_a), json={
        "numero": "1", "tantiemes": 1000, "statut_occupation": "squat"})
    assert r.status_code == 422


def test_proprietaire_occupant_derive_du_compte(client, db, copro_a, syndic_a, token_a):
    """« Propriétaire occupant » suit la case du compte lié, dans les deux sens."""
    p = _personne(db, copro_a)
    _lot(db, copro_a, proprietaire_id=p.id)

    # Fiche sans compte : pas « propriétaire occupant »
    lots = client.get("/api/lots", headers=auth(token_a)).json()
    assert lots[0]["proprietaire_occupant"] is False

    # Compte lié mais case décochée : toujours faux
    r = client.post("/api/auth/users", headers=auth(token_a), json={
        "email": "paul@test.fr", "password": "test1234", "nom": "Durand",
        "prenom": "Paul", "role": "membre", "personne_id": p.id, "est_occupant": False})
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    assert client.get("/api/lots", headers=auth(token_a)).json()[0]["proprietaire_occupant"] is False

    # On coche « occupe son logement » : le lot devient « propriétaire occupant »
    assert client.put(f"/api/auth/users/{uid}", headers=auth(token_a), json={
        "email": "paul@test.fr", "nom": "Durand", "prenom": "Paul", "role": "membre",
        "personne_id": p.id, "est_occupant": True}).status_code == 200
    assert client.get("/api/lots", headers=auth(token_a)).json()[0]["proprietaire_occupant"] is True

    # On décoche : il disparaît
    assert client.put(f"/api/auth/users/{uid}", headers=auth(token_a), json={
        "email": "paul@test.fr", "nom": "Durand", "prenom": "Paul", "role": "membre",
        "personne_id": p.id, "est_occupant": False}).status_code == 200
    assert client.get("/api/lots", headers=auth(token_a)).json()[0]["proprietaire_occupant"] is False


def test_personnes_derivees(client, db, copro_a, syndic_a, token_a):
    """GET /personnes : « propriétaire » vient des lots, « occupe son logement » du compte."""
    p_owner = _personne(db, copro_a, nom="Dubois", email="dubois@test.fr")
    p_autre = _personne(db, copro_a, nom="Martin", email="martin@test.fr")
    _lot(db, copro_a, proprietaire_id=p_owner.id)
    assert client.post("/api/auth/users", headers=auth(token_a), json={
        "email": "dubois@test.fr", "password": "test1234", "nom": "Dubois",
        "prenom": "Paul", "role": "membre", "personne_id": p_owner.id,
        "est_occupant": True}).status_code == 200

    items = {x["id"]: x for x in client.get("/api/personnes", headers=auth(token_a)).json()}
    assert items[p_owner.id]["est_proprietaire"] is True
    assert items[p_owner.id]["a_un_compte"] is True
    assert items[p_owner.id]["compte_occupant"] is True
    assert items[p_autre.id]["est_proprietaire"] is False
    assert items[p_autre.id]["a_un_compte"] is False
    assert items[p_autre.id]["compte_occupant"] is False
