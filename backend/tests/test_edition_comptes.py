"""Modification d'un mouvement et d'une ligne de budget (page Comptes).

Règles retenues :
- le syndic modifie un mouvement (date, libellé, type, catégorie, montant, lot) ou une ligne de
  budget ; un copropriétaire ne le peut pas (403) ; un élément d'une autre copropriété : 404 ;
- type (encaissement | dépense) et catégorie contrôlés, à la création comme à la modification (422) ;
- le lot et l'appel rattachés doivent appartenir à la copropriété (422) ;
- la modification d'un mouvement est inscrite au journal d'audit, avec l'avant et l'après.
"""
from app.models.audit import AuditLog
from app.models.lot import Lot
from app.core.security import create_access_token
from tests.conftest import _make_membre, auth


def _exercice(client, token):
    r = client.post("/api/exercices", json={"annee": 2026}, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _mouvement(client, token, ex_id, **champs):
    corps = {"date": "2026-02-01", "libelle": "Facture EDF", "type": "depense",
             "categorie": "energie", "montant": 120.0, **champs}
    r = client.post(f"/api/exercices/{ex_id}/mouvements", json=corps, headers=auth(token))
    return r


def test_modifier_un_mouvement(client, db, copro_a, syndic_a, token_a):
    ex_id = _exercice(client, token_a)
    m = _mouvement(client, token_a, ex_id).json()
    corps = {"date": "2026-02-03", "libelle": "Facture EDF janvier", "type": "depense",
             "categorie": "energie", "montant": "134.56"}
    r = client.put(f"/api/mouvements/{m['id']}", json=corps, headers=auth(token_a))
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["date"], d["libelle"], d["montant"]) == ("2026-02-03", "Facture EDF janvier", 134.56)
    liste = client.get(f"/api/exercices/{ex_id}/mouvements", headers=auth(token_a)).json()
    assert [x["montant"] for x in liste] == [134.56]
    journal = db.query(AuditLog).filter(AuditLog.action == "mouvement_modifie").all()
    assert len(journal) == 1
    assert "120,00" in journal[0].detail and "134,56" in journal[0].detail


def test_changer_le_type(client, db, copro_a, syndic_a, token_a):
    ex_id = _exercice(client, token_a)
    m = _mouvement(client, token_a, ex_id).json()
    corps = {**{k: m[k] for k in ("date", "libelle", "categorie", "montant")}, "type": "encaissement",
             "categorie": "charges"}
    assert client.put(f"/api/mouvements/{m['id']}", json=corps, headers=auth(token_a)).json()["type"] == "encaissement"


def test_type_et_categorie_controles(client, db, copro_a, syndic_a, token_a):
    ex_id = _exercice(client, token_a)
    assert _mouvement(client, token_a, ex_id, type="retrait").status_code == 422
    assert _mouvement(client, token_a, ex_id, categorie="divers").status_code == 422
    m = _mouvement(client, token_a, ex_id).json()
    corps = {"date": "2026-02-01", "libelle": "x", "type": "depense", "categorie": "inconnue", "montant": 1}
    assert client.put(f"/api/mouvements/{m['id']}", json=corps, headers=auth(token_a)).status_code == 422


def test_lot_d_une_autre_copropriete_refuse(client, db, copro_a, copro_b, syndic_a, token_a):
    ex_id = _exercice(client, token_a)
    lot_b = Lot(copropriete_id=copro_b.id, numero="9", tantiemes=100)
    db.add(lot_b)
    db.commit()
    assert _mouvement(client, token_a, ex_id, type="encaissement", categorie="charges",
                      lot_id=lot_b.id).status_code == 422
    m = _mouvement(client, token_a, ex_id).json()
    corps = {"date": "2026-02-01", "libelle": "x", "type": "encaissement", "categorie": "charges",
             "montant": 1, "lot_id": lot_b.id}
    assert client.put(f"/api/mouvements/{m['id']}", json=corps, headers=auth(token_a)).status_code == 422


def test_mouvement_d_une_autre_copropriete(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b):
    ex_id = _exercice(client, token_a)
    m = _mouvement(client, token_a, ex_id).json()
    corps = {"date": "2026-02-01", "libelle": "x", "type": "depense", "categorie": "energie", "montant": 1}
    assert client.put(f"/api/mouvements/{m['id']}", json=corps, headers=auth(token_b)).status_code == 404


def test_reserve_au_syndic(client, db, copro_a, syndic_a, token_a):
    ex_id = _exercice(client, token_a)
    m = _mouvement(client, token_a, ex_id).json()
    membre = _make_membre(db, "membre@test.fr", copro_a)
    tok = create_access_token(membre.id, copro_a.id)
    corps = {"date": "2026-02-01", "libelle": "x", "type": "depense", "categorie": "energie", "montant": 1}
    assert client.put(f"/api/mouvements/{m['id']}", json=corps, headers=auth(tok)).status_code == 403


def test_modifier_une_ligne_de_budget(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b):
    ex_id = _exercice(client, token_a)
    r = client.post(f"/api/exercices/{ex_id}/budget", json={"libelle": "Électricité", "montant": 800},
                    headers=auth(token_a))
    ligne = r.json()
    r = client.put(f"/api/budget/{ligne['id']}", json={"libelle": "Électricité parties communes", "montant": 950},
                   headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert (r.json()["libelle"], r.json()["montant"]) == ("Électricité parties communes", 950)
    assert client.put(f"/api/budget/{ligne['id']}", json={"libelle": "x", "montant": 1},
                      headers=auth(token_b)).status_code == 404
