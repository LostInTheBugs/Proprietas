"""Second vote immédiat (passerelles art. 25-1 et 26-1) : résultat exposé par l'API,
création de la résolution liée, refus quand la passerelle n'est pas ouverte."""
from datetime import date

from app.models.ag import AG
from app.models.lot import Lot
from tests.conftest import auth


def _ag_avec_4_lots(db, copro):
    """4 lots de 250 sans propriétaire saisi : 4 membres distincts, 1000 voix."""
    lots = [Lot(copropriete_id=copro.id, numero=str(i), tantiemes=250) for i in range(1, 5)]
    db.add_all(lots)
    ag = AG(copropriete_id=copro.id, date=date(2026, 11, 20))
    db.add(ag)
    db.commit()
    return ag, lots


def _resolution(client, token, ag, majorite, votes):
    r = client.post(f"/api/ag/{ag.id}/resolutions", headers=auth(token),
                    json={"numero": 3, "libelle": "Ravalement", "majorite": majorite})
    assert r.status_code == 200, r.text
    res_id = r.json()["id"]
    for lot, voix in votes:
        v = client.post(f"/api/resolutions/{res_id}/votes", headers=auth(token),
                        json={"lot_id": lot.id, "voix": voix})
        assert v.status_code == 200, v.text
    return client.post(f"/api/resolutions/{res_id}/calculer", headers=auth(token)).json()


def test_resultat_expose_membres_et_passerelle(client, db, copro_a, token_a):
    ag, lots = _ag_avec_4_lots(db, copro_a)
    res = _resolution(client, token_a, ag, "art25",
                      [(lots[0], "pour"), (lots[1], "pour"), (lots[2], "contre")])
    assert res["statut"] == "rejetee"
    assert res["resultat"]["second_vote_possible"] == "art24"
    assert res["resultat"]["nb_membres"] == 4
    assert res["resultat"]["membres_pour"] == 2
    assert res["resultat"]["reduction_art22"] is None
    assert res["second_vote_de_id"] is None


def test_second_vote_cree_une_resolution_liee(client, db, copro_a, token_a):
    ag, lots = _ag_avec_4_lots(db, copro_a)
    res = _resolution(client, token_a, ag, "art25",
                      [(lots[0], "pour"), (lots[1], "pour"), (lots[2], "contre")])
    r = client.post(f"/api/resolutions/{res['id']}/second-vote", headers=auth(token_a))
    assert r.status_code == 200, r.text
    sv = r.json()
    assert sv["majorite"] == "art24"
    assert sv["second_vote_de_id"] == res["id"]
    assert sv["numero"] == 3
    assert "art. 25-1" in sv["libelle"]
    assert sv["votes"] == []
    # Un seul second vote par résolution
    r2 = client.post(f"/api/resolutions/{res['id']}/second-vote", headers=auth(token_a))
    assert r2.status_code == 409, r2.text


def test_second_vote_refuse_si_passerelle_fermee(client, db, copro_a, token_a):
    ag, lots = _ag_avec_4_lots(db, copro_a)
    res = _resolution(client, token_a, ag, "art25",
                      [(lots[0], "pour"), (lots[1], "contre"), (lots[2], "contre")])  # 250 < 1/3
    assert res["resultat"]["second_vote_possible"] is None
    r = client.post(f"/api/resolutions/{res['id']}/second-vote", headers=auth(token_a))
    assert r.status_code == 400, r.text


def test_second_vote_isole_par_copropriete(client, db, copro_a, token_a, token_b):
    ag, lots = _ag_avec_4_lots(db, copro_a)
    res = _resolution(client, token_a, ag, "art25",
                      [(lots[0], "pour"), (lots[1], "pour"), (lots[2], "contre")])
    r = client.post(f"/api/resolutions/{res['id']}/second-vote", headers=auth(token_b))
    assert r.status_code == 404, r.text
    # 404 « métier » (objet d'une autre copro), pas 404 « route inexistante »
    assert r.json()["detail"] == "Résolution introuvable"


def test_supprimer_resolution_supprime_son_second_vote(client, db, copro_a, token_a):
    ag, lots = _ag_avec_4_lots(db, copro_a)
    res = _resolution(client, token_a, ag, "art25",
                      [(lots[0], "pour"), (lots[1], "pour"), (lots[2], "contre")])
    sv = client.post(f"/api/resolutions/{res['id']}/second-vote", headers=auth(token_a)).json()
    assert client.delete(f"/api/resolutions/{res['id']}", headers=auth(token_a)).status_code == 200
    restantes = client.get(f"/api/ag", headers=auth(token_a)).json()
    ids = [r["id"] for a in restantes for r in a.get("resolutions", [])]
    assert res["id"] not in ids and sv["id"] not in ids
