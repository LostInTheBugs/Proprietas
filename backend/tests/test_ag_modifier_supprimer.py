"""Modifier ou supprimer une AG saisie par erreur ou d'essai (demande de Fred, 20/11/2026)."""
from datetime import date, timedelta

from app.models.ag import AG, AgReponse, Resolution, Vote, VoteCorrespondance
from app.models.audit import AuditLog
from app.models.exercice import Exercice
from tests.conftest import auth
from tests.test_ag_presences import _ag, _immeuble


def test_supprimer_une_ag_et_tout_ce_qui_en_depend(client, db, copro_a, syndic_a, token_a):
    marie, paul = _immeuble(db, copro_a, syndic_a, [450, 450])
    ag_id = _ag(client, token_a)
    rid = client.post(f"/api/ag/{ag_id}/resolutions", json={"libelle": "Ravalement"}, headers=auth(token_a)).json()["id"]
    client.put(f"/api/ag/{ag_id}/presences/{paul.id}", json={"reponse": "present"}, headers=auth(token_a))
    client.put(f"/api/ag/{ag_id}/correspondance/{marie.id}", json={"recu_le": str(date.today()), "votes": {rid: "pour"}},
               headers=auth(token_a))
    lot = next(l for l in db.get(AG, ag_id).copropriete.lots if l.proprietaire_id == paul.id)
    client.post(f"/api/resolutions/{rid}/votes", json={"lot_id": lot.id, "voix": "contre"}, headers=auth(token_a))
    client.post(f"/api/ag/{ag_id}/creneaux", json={"debut": f"{date.today() + timedelta(days=40)}T18:00:00"},
                headers=auth(token_a))
    r = client.delete(f"/api/ag/{ag_id}", headers=auth(token_a))
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(AG, ag_id) is None
    for modele in (Resolution, Vote, AgReponse, VoteCorrespondance):
        assert db.query(modele).count() == 0, modele
    assert db.query(AuditLog).filter(AuditLog.action == "ag_supprimee").count() == 1
    assert client.get("/api/ag", headers=auth(token_a)).json() == []


def test_approbation_des_comptes_suit_l_ag(client, db, copro_a, syndic_a, token_a):
    marie, = _immeuble(db, copro_a, syndic_a, [1000])
    annee = date.today().year - 1
    ex = client.post("/api/exercices", json={"annee": annee}, headers=auth(token_a)).json()["id"]
    client.put(f"/api/exercices/{ex}", json={"annee": annee, "cloture": True}, headers=auth(token_a))
    jour = date.today() - timedelta(days=2)
    ag_id = client.post("/api/ag", json={"date": str(jour), "statut": "terminee"}, headers=auth(token_a)).json()["id"]
    rid = client.post(f"/api/ag/{ag_id}/resolutions", json={"libelle": "Comptes", "nature": "approbation_comptes",
                                                             "exercice_id": ex}, headers=auth(token_a)).json()["id"]
    lot = next(l for l in db.get(AG, ag_id).copropriete.lots if l.proprietaire_id == marie.id)
    client.post(f"/api/resolutions/{rid}/votes", json={"lot_id": lot.id, "voix": "pour"}, headers=auth(token_a))
    assert client.post(f"/api/resolutions/{rid}/calculer", headers=auth(token_a)).json()["statut"] == "adoptee"
    db.expire_all()
    assert db.get(Exercice, ex).comptes_approuves_le == jour
    # Date corrigée : l'approbation suit.
    nouveau = jour - timedelta(days=1)
    r = client.put(f"/api/ag/{ag_id}", json={"date": str(nouveau), "statut": "terminee", "lieu": "Salle"},
                   headers=auth(token_a))
    assert r.status_code == 200 and r.json()["lieu"] == "Salle"
    db.expire_all()
    assert db.get(Exercice, ex).comptes_approuves_le == nouveau
    # AG supprimée : l'approbation est retirée.
    r = client.delete(f"/api/ag/{ag_id}", headers=auth(token_a))
    assert r.json()["approbations_retirees"] == [annee]
    db.expire_all()
    assert db.get(Exercice, ex).comptes_approuves_le is None


def test_droits(client, db, copro_a, syndic_a, token_a, token_b):
    marie, = _immeuble(db, copro_a, syndic_a, [500])
    ag_id = _ag(client, token_a)
    from app.core.security import create_access_token
    t = create_access_token(marie.id, copro_a.id)
    assert client.delete(f"/api/ag/{ag_id}", headers=auth(t)).status_code == 403
    assert client.delete(f"/api/ag/{ag_id}", headers=auth(token_b)).status_code == 404
    assert client.put(f"/api/ag/{ag_id}", json={"date": "2030-01-01"}, headers=auth(token_b)).status_code == 404
