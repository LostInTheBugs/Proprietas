"""Occupation des lots — déclarée lot par lot (« occupant » / « loué » / « vacant »).

Modèle « zéro fiche » : le propriétaire est un COMPTE utilisateur. Chaque lot
porte `statut_occupation` : "" (non renseigné) | "occupant" | "loue" | "vacant".
« occupant » = le propriétaire occupe son logement (badge « propriétaire
occupant »). Jamais de nom de locataire stocké (RGPD).

Le propriétaire règle lui-même l'occupation de ses lots depuis Réglages → Mes
lots (PUT /api/lots/{id}/occupation) ; le syndic règle n'importe quel lot.
"""
from tests.conftest import auth, _make_membre
from app.core.security import create_access_token


def _lot(db, copro, numero="1", **kw):
    from app.models.lot import Lot
    lot = Lot(copropriete_id=copro.id, numero=numero, tantiemes=1000, **kw)
    db.add(lot)
    db.commit()
    db.refresh(lot)
    return lot


def test_lot_statut_occupation_roundtrip(client, db, copro_a, syndic_a, token_a):
    """« occupant » / « loué » / « vacant » se saisissent sur le lot ; le reste est refusé."""
    membre = _make_membre(db, "paul@test.fr", copro_a)
    r = client.post("/api/lots", headers=auth(token_a), json={
        "numero": "1", "tantiemes": 1000, "proprietaire_id": membre.id, "statut_occupation": "loue"})
    assert r.status_code == 200, r.text
    assert r.json()["statut_occupation"] == "loue"
    assert r.json()["proprietaire_nom"] == "Membre paul@test.fr"
    lot_id = r.json()["id"]

    r = client.put(f"/api/lots/{lot_id}", headers=auth(token_a), json={
        "numero": "1", "tantiemes": 1000, "proprietaire_id": membre.id, "statut_occupation": "vacant"})
    assert r.status_code == 200, r.text
    assert r.json()["statut_occupation"] == "vacant"

    r = client.put(f"/api/lots/{lot_id}", headers=auth(token_a), json={
        "numero": "1", "tantiemes": 1000, "proprietaire_id": membre.id, "statut_occupation": "squat"})
    assert r.status_code == 422


def test_proprietaire_occupant_derive_du_lot(client, db, copro_a, syndic_a, token_a):
    """Le badge « propriétaire occupant » suit le statut du lot, dans les deux sens."""
    membre = _make_membre(db, "paul@test.fr", copro_a)
    _lot(db, copro_a, proprietaire_id=membre.id)

    lots = client.get("/api/lots", headers=auth(token_a)).json()
    assert lots[0]["proprietaire_occupant"] is False
    assert lots[0]["statut_occupation"] == ""

    # « occupant » : le lot s'affiche « propriétaire occupant »
    assert client.put(f"/api/lots/{lots[0]['id']}/occupation", headers=auth(token_a),
                      json={"statut_occupation": "occupant"}).status_code == 200
    lots = client.get("/api/lots", headers=auth(token_a)).json()
    assert lots[0]["proprietaire_occupant"] is True

    # « loué » : il disparaît (et le statut suit)
    assert client.put(f"/api/lots/{lots[0]['id']}/occupation", headers=auth(token_a),
                      json={"statut_occupation": "loue"}).status_code == 200
    lots = client.get("/api/lots", headers=auth(token_a)).json()
    assert lots[0]["proprietaire_occupant"] is False
    assert lots[0]["statut_occupation"] == "loue"

    # Valeur inconnue → 422
    assert client.put(f"/api/lots/{lots[0]['id']}/occupation", headers=auth(token_a),
                      json={"statut_occupation": "squat"}).status_code == 422


def test_occupation_par_le_proprietaire(client, db, copro_a, syndic_a, token_a):
    """Le propriétaire règle SES lots lui-même ; ceux des autres → 403 (syndic: tous)."""
    alice = _make_membre(db, "alice@test.fr", copro_a)
    bob = _make_membre(db, "bob@test.fr", copro_a)
    lot_alice = _lot(db, copro_a, numero="1", proprietaire_id=alice.id)
    lot_bob = _lot(db, copro_a, numero="2", proprietaire_id=bob.id)
    token_alice = create_access_token(alice.id, copro_a.id)
    token_bob = create_access_token(bob.id, copro_a.id)

    # Alice règle son lot (« partie de ses lots » : elle peut mixer les statuts)
    r = client.put(f"/api/lots/{lot_alice.id}/occupation", headers=auth(token_alice),
                   json={"statut_occupation": "occupant"})
    assert r.status_code == 200, r.text
    assert r.json()["statut_occupation"] == "occupant"

    # Alice ne peut PAS régler le lot de Bob
    assert client.put(f"/api/lots/{lot_bob.id}/occupation", headers=auth(token_alice),
                      json={"statut_occupation": "vacant"}).status_code == 403
    # Bob, lui, le peut
    assert client.put(f"/api/lots/{lot_bob.id}/occupation", headers=auth(token_bob),
                      json={"statut_occupation": "vacant"}).status_code == 200
    # Le syndic aussi (n'importe quel lot)
    assert client.put(f"/api/lots/{lot_bob.id}/occupation", headers=auth(token_a),
                      json={"statut_occupation": "loue"}).status_code == 200


def test_lot_proprietaire_isole(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a):
    """Le propriétaire doit appartenir à la copropriété du lot (isolation)."""
    r = client.post("/api/lots", headers=auth(token_a), json={
        "numero": "1", "tantiemes": 1000, "proprietaire_id": syndic_b.id})
    assert r.status_code == 400
    assert "introuvable" in r.text
    # Un lot sans propriétaire reste possible (nouveau lot, vente en cours…)
    r = client.post("/api/lots", headers=auth(token_a), json={"numero": "2", "tantiemes": 0})
    assert r.status_code == 200, r.text
    assert r.json()["proprietaire_nom"] == ""
