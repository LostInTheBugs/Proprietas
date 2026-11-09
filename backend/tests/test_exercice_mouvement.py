"""Changer l'exercice d'un mouvement (saisi dans la mauvaise année).

Règles retenues :
- en modifiant un mouvement, le syndic peut choisir un autre exercice de la copropriété (sinon 422) ;
  sans exercice indiqué, il ne change pas ; le changement est inscrit au journal d'audit ;
- « reclasser » : les mouvements d'un exercice dont la date est d'une autre année sont déplacés vers
  l'exercice de leur année (créé s'il manque, clôturé si l'année est passée) ; « simuler » liste sans
  rien changer ;
- une dépense ne quitte pas (et n'entre pas dans) un exercice dont les charges sont déjà régularisées :
  la régularisation deviendrait fausse (422).
"""
from datetime import date

from app.models.appel import AppelFonds
from app.models.audit import AuditLog
from app.models.exercice import Exercice
from app.models.mouvement import Mouvement
from tests.conftest import auth

Y = date.today().year


def _exercices(client, token):
    ids = {}
    for annee in (Y - 1, Y):
        r = client.post("/api/exercices", json={"annee": annee}, headers=auth(token))
        assert r.status_code == 200, r.text
        ids[annee] = r.json()["id"]
    return ids


def _mouvement(client, token, ex_id, jour, **champs):
    corps = {"date": jour, "libelle": "Facture EDF", "type": "depense", "categorie": "energie",
             "montant": 100, **champs}
    r = client.post(f"/api/exercices/{ex_id}/mouvements", json=corps, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _liste(client, token, ex_id):
    return client.get(f"/api/exercices/{ex_id}/mouvements", headers=auth(token)).json()


def test_changer_l_exercice_en_modifiant(client, db, copro_a, syndic_a, token_a):
    ex = _exercices(client, token_a)
    m = _mouvement(client, token_a, ex[Y], f"{Y - 1}-12-15")
    corps = {k: m[k] for k in ("date", "libelle", "type", "categorie", "montant")}
    r = client.put(f"/api/mouvements/{m['id']}", json={**corps, "exercice_id": ex[Y - 1]}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert r.json()["exercice_id"] == ex[Y - 1]
    assert _liste(client, token_a, ex[Y]) == [] and len(_liste(client, token_a, ex[Y - 1])) == 1
    detail = db.query(AuditLog).filter(AuditLog.action == "mouvement_modifie").one().detail
    assert f"exercice {Y} → {Y - 1}" in detail


def test_sans_exercice_indique_rien_ne_change(client, db, copro_a, syndic_a, token_a):
    ex = _exercices(client, token_a)
    m = _mouvement(client, token_a, ex[Y], f"{Y}-02-01")
    corps = {k: m[k] for k in ("date", "libelle", "type", "categorie")} | {"montant": 120}
    r = client.put(f"/api/mouvements/{m['id']}", json=corps, headers=auth(token_a))
    assert r.status_code == 200 and r.json()["exercice_id"] == ex[Y]


def test_exercice_d_une_autre_copropriete_refuse(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b):
    ex = _exercices(client, token_a)
    ex_b = client.post("/api/exercices", json={"annee": Y - 1}, headers=auth(token_b)).json()["id"]
    m = _mouvement(client, token_a, ex[Y], f"{Y}-02-01")
    corps = {k: m[k] for k in ("date", "libelle", "type", "categorie", "montant")} | {"exercice_id": ex_b}
    assert client.put(f"/api/mouvements/{m['id']}", json=corps, headers=auth(token_a)).status_code == 422
    assert _liste(client, token_a, ex[Y])[0]["id"] == m["id"]


def test_reclasser_simulation_puis_deplacement(client, db, copro_a, syndic_a, token_a):
    ex = _exercices(client, token_a)
    a = _mouvement(client, token_a, ex[Y], f"{Y - 1}-11-03")
    b = _mouvement(client, token_a, ex[Y], f"{Y - 1}-12-20", type="encaissement", categorie="charges")
    _mouvement(client, token_a, ex[Y], f"{Y}-01-10")
    url = f"/api/exercices/{ex[Y]}/mouvements/reclasser"
    r = client.post(url, json={"simuler": True}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert sorted(x["id"] for x in r.json()["mouvements"]) == sorted([a["id"], b["id"]])
    assert all(x["vers"] == Y - 1 for x in r.json()["mouvements"])
    assert len(_liste(client, token_a, ex[Y])) == 3
    r = client.post(url, json={"simuler": False}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert len(_liste(client, token_a, ex[Y])) == 1 and len(_liste(client, token_a, ex[Y - 1])) == 2
    assert db.query(AuditLog).filter(AuditLog.action == "mouvements_reclasses").count() == 1


def test_reclasser_cree_l_exercice_manquant(client, db, copro_a, syndic_a, token_a):
    ex_id = client.post("/api/exercices", json={"annee": Y}, headers=auth(token_a)).json()["id"]
    _mouvement(client, token_a, ex_id, f"{Y - 2}-06-01")
    r = client.post(f"/api/exercices/{ex_id}/mouvements/reclasser", json={"simuler": False}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    nouveau = db.query(Exercice).filter(Exercice.annee == Y - 2).one()
    assert nouveau.cloture is True
    assert db.query(Mouvement).one().exercice_id == nouveau.id


def test_depense_d_un_exercice_regularise_bloquee(client, db, copro_a, syndic_a, token_a):
    ex = _exercices(client, token_a)
    m = _mouvement(client, token_a, ex[Y], f"{Y - 1}-12-15")
    # Les charges de Y-1 sont déjà régularisées : y faire entrer une dépense fausserait la régularisation.
    db.add(AppelFonds(exercice_id=ex[Y - 1], regularisation_de_id=ex[Y - 1], libelle=f"Régularisation des charges {Y - 1}",
                      date_emission=date(Y, 3, 1), date_echeance=date(Y, 3, 31), montant_total=0))
    db.commit()
    corps = {k: m[k] for k in ("date", "libelle", "type", "categorie", "montant")} | {"exercice_id": ex[Y - 1]}
    r = client.put(f"/api/mouvements/{m['id']}", json=corps, headers=auth(token_a))
    assert r.status_code == 422 and "régularisées" in r.json()["detail"]
    r = client.post(f"/api/exercices/{ex[Y]}/mouvements/reclasser", json={"simuler": False}, headers=auth(token_a))
    assert r.status_code == 422
    assert _liste(client, token_a, ex[Y])[0]["id"] == m["id"]
