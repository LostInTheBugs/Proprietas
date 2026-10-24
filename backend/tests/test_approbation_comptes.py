"""Approbation des comptes et décompte de l'article 19-2 (loi n° 65-557).

Art. 19-2 : après une mise en demeure restée infructueuse 30 jours, deviennent exigibles les
provisions non encore échues ET « les sommes restant dues appelées au titre des exercices
précédents APRÈS APPROBATION DES COMPTES ».

Avant : tout exercice antérieur était retenu (le code l'appelait lui-même un « proxy ») ;
la clôture d'un exercice et l'approbation de ses comptes par l'AG étaient confondues.
Nouveau :
- exercices.comptes_approuves_le (date de l'AG qui a approuvé les comptes) ;
- saisie manuelle (exercice clôturé, date passée, pas avant l'année de l'exercice) ;
- ou automatique : résolution d'objet « approbation des comptes », liée à l'exercice,
  adoptée → date de l'AG ; recalculée rejetée → date retirée ;
- 19-2 : un exercice antérieur NON approuvé est exclu et signalé.
"""
from datetime import date, timedelta

import pytest

from app.models.exercice import Exercice
from app.models.lot import Lot
from tests.conftest import auth

AUJOURDHUI = date.today()
HIER = AUJOURDHUI - timedelta(days=1)


def _exercice(db, copro, annee, cloture=True, approuve=None):
    ex = Exercice(copropriete_id=copro.id, annee=annee, cloture=cloture)
    db.add(ex)
    db.commit()
    db.refresh(ex)
    if approuve is not None:
        ex.comptes_approuves_le = approuve
        db.commit()
    return ex


def _put(client, token_a, ex, **corps):
    return client.put(f"/api/exercices/{ex.id}", json={"annee": ex.annee, **corps}, headers=auth(token_a))


# ---------------------------------------------------------------- saisie sur l'exercice
def test_approbation_saisie_et_relue(client, token_a, db, copro_a):
    ex = _exercice(db, copro_a, AUJOURDHUI.year - 1)
    r = _put(client, token_a, ex, cloture=True, comptes_approuves_le=HIER.isoformat())
    assert r.status_code == 200, r.text
    assert r.json()["comptes_approuves_le"] == HIER.isoformat()
    liste = client.get("/api/exercices", headers=auth(token_a)).json()
    assert liste[0]["comptes_approuves_le"] == HIER.isoformat()


def test_approbation_exige_un_exercice_cloture(client, token_a, db, copro_a):
    ex = _exercice(db, copro_a, AUJOURDHUI.year - 1, cloture=False)
    r = _put(client, token_a, ex, cloture=False, comptes_approuves_le=HIER.isoformat())
    assert r.status_code == 422, r.text


def test_approbation_dans_le_futur_refusee(client, token_a, db, copro_a):
    ex = _exercice(db, copro_a, AUJOURDHUI.year - 1)
    demain = (AUJOURDHUI + timedelta(days=1)).isoformat()
    assert _put(client, token_a, ex, cloture=True, comptes_approuves_le=demain).status_code == 422


def test_approbation_avant_l_annee_de_l_exercice_refusee(client, token_a, db, copro_a):
    ex = _exercice(db, copro_a, AUJOURDHUI.year)
    avant = date(AUJOURDHUI.year - 1, 6, 30).isoformat()
    assert _put(client, token_a, ex, cloture=True, comptes_approuves_le=avant).status_code == 422


def test_approbation_retiree(client, token_a, db, copro_a):
    ex = _exercice(db, copro_a, AUJOURDHUI.year - 1, approuve=HIER)
    r = _put(client, token_a, ex, cloture=True, comptes_approuves_le=None)
    assert r.status_code == 200 and r.json()["comptes_approuves_le"] is None


def test_cloture_seule_ne_vaut_pas_approbation(client, token_a, db, copro_a):
    ex = _exercice(db, copro_a, AUJOURDHUI.year - 1, cloture=False)
    r = _put(client, token_a, ex, cloture=True)
    assert r.status_code == 200 and r.json()["comptes_approuves_le"] is None


# ---------------------------------------------------------------- résolution « approbation des comptes »
@pytest.fixture()
def ag_et_lots(client, token_a, db, copro_a):
    db.add_all([Lot(copropriete_id=copro_a.id, numero=str(i), tantiemes=t)
                for i, t in ((1, 400), (2, 300), (3, 300))])
    db.commit()
    ag = client.post("/api/ag", json={"date": HIER.isoformat(), "type_ag": "annuelle", "rappel_jours": 0},
                     headers=auth(token_a)).json()
    lots = db.query(Lot).filter(Lot.copropriete_id == copro_a.id).order_by(Lot.id).all()
    return ag, lots


def _resolution(client, token_a, ag, **corps):
    base = {"numero": 1, "libelle": "Approbation des comptes", "majorite": "art24",
            "nature": "approbation_comptes"}
    return client.post(f"/api/ag/{ag['id']}/resolutions", json={**base, **corps}, headers=auth(token_a))


def _voter(client, token_a, res_id, lots, voix):
    for lot, v in zip(lots, voix):
        client.post(f"/api/resolutions/{res_id}/votes", json={"lot_id": lot.id, "voix": v}, headers=auth(token_a))
    return client.post(f"/api/resolutions/{res_id}/calculer", headers=auth(token_a)).json()


def test_approbation_sans_exercice_refusee(client, token_a, ag_et_lots):
    ag, _ = ag_et_lots
    r = _resolution(client, token_a, ag)
    assert r.status_code == 422, r.text


def test_approbation_d_un_exercice_d_une_autre_copro(client, token_a, ag_et_lots, db, copro_b):
    ag, _ = ag_et_lots
    autre = _exercice(db, copro_b, AUJOURDHUI.year - 1)
    assert _resolution(client, token_a, ag, exercice_id=autre.id).status_code == 404


def test_exercice_ignore_si_autre_objet(client, token_a, ag_et_lots, db, copro_a):
    ag, _ = ag_et_lots
    ex = _exercice(db, copro_a, AUJOURDHUI.year - 1)
    r = _resolution(client, token_a, ag, nature="autre", exercice_id=ex.id)
    assert r.status_code == 200 and r.json()["exercice_id"] is None


def test_resolution_adoptee_approuve_les_comptes(client, token_a, ag_et_lots, db, copro_a):
    ag, lots = ag_et_lots
    ex = _exercice(db, copro_a, AUJOURDHUI.year - 1, cloture=False)
    res = _resolution(client, token_a, ag, exercice_id=ex.id).json()
    assert res["exercice_id"] == ex.id
    assert _voter(client, token_a, res["id"], lots, ("pour", "pour", "contre"))["statut"] == "adoptee"
    db.refresh(ex)
    assert ex.comptes_approuves_le == HIER and ex.cloture is True

    # Recalcul après correction des votes : rejetée → l'approbation tirée de cette AG est retirée.
    assert _voter(client, token_a, res["id"], lots, ("contre", "contre", "pour"))["statut"] == "rejetee"
    db.refresh(ex)
    assert ex.comptes_approuves_le is None


def test_rejet_ne_retire_pas_une_approbation_d_une_autre_date(client, token_a, ag_et_lots, db, copro_a):
    ag, lots = ag_et_lots
    autre_date = HIER - timedelta(days=10)
    ex = _exercice(db, copro_a, AUJOURDHUI.year - 1, approuve=autre_date)
    res = _resolution(client, token_a, ag, exercice_id=ex.id).json()
    assert _voter(client, token_a, res["id"], lots, ("contre", "contre", "contre"))["statut"] == "rejetee"
    db.refresh(ex)
    assert ex.comptes_approuves_le == autre_date


def test_second_vote_garde_l_objet_et_l_exercice(client, token_a, ag_et_lots, db, copro_a):
    # Correctif lié : le second vote (passerelle art. 25-1) perdait la « nature » de la résolution.
    ag, lots = ag_et_lots
    res = _resolution(client, token_a, ag, nature="budget", majorite="art25").json()
    _voter(client, token_a, res["id"], lots, ("pour", "contre", "contre"))   # 400/1000 : ≥ 1/3, < 1/2
    r = client.post(f"/api/resolutions/{res['id']}/second-vote", headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert r.json()["nature"] == "budget"
