"""Consultation écrite : loi n° 65-557, art. 41-12 (ordonnance n° 2019-1101).

Dans une PETITE copropriété (art. 41-8), le syndicat peut décider sans assemblée générale,
par consultation écrite, à condition :
- que la décision soit prise à l'UNANIMITÉ des voix de tous les copropriétaires ;
- qu'elle ne porte ni sur le VOTE DU BUDGET PRÉVISIONNEL ni sur l'APPROBATION DES COMPTES.

Avant : consultation écrite ouverte à toute copropriété, avec la majorité au choix.
Nouveau : la « nature » d'une résolution (autre | budget | approbation_comptes) est saisie,
ce qui permet de bloquer les sujets exclus (et servira à la tâche 21 : approbation des comptes).
Une consultation écrite déjà créée dans une copropriété qui n'est pas « petite » reste
modifiable (on ne casse pas l'existant), mais n'accepte que des résolutions conformes.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.models.ag import AG
from app.models.exercice import BudgetLine, Exercice
from app.models.lot import Lot
from tests.conftest import auth

DATE = "2026-12-10"


def _lots(db, copro, n, type_lot="appartement"):
    db.add_all([Lot(copropriete_id=copro.id, numero=str(i + 1), type=type_lot, tantiemes=100)
                for i in range(n)])
    db.commit()


@pytest.fixture()
def petite(db, copro_a):
    _lots(db, copro_a, 3)                     # 3 logements : petite copropriété (art. 41-8)
    return copro_a


@pytest.fixture()
def grande(db, copro_a):
    _lots(db, copro_a, 6)                     # 6 logements, aucun budget : régime général
    return copro_a


def _ag(client, token_a, type_ag="consultation_ecrite"):
    return client.post("/api/ag", json={"date": DATE, "type_ag": type_ag, "rappel_jours": 0},
                       headers=auth(token_a))


def _resolution(client, token_a, ag_id, majorite="unanimite", nature=None, exercice_id=None):
    corps = {"numero": 1, "libelle": "Remplacement de la porte d'entrée", "majorite": majorite}
    if nature is not None:
        corps["nature"] = nature
    if exercice_id is not None:
        corps["exercice_id"] = exercice_id
    return client.post(f"/api/ag/{ag_id}/resolutions", json=corps, headers=auth(token_a))


# ---------------------------------------------------------------- réservée aux petites copropriétés
def test_consultation_refusee_hors_petite_copropriete(client, token_a, grande):
    r = _ag(client, token_a)
    assert r.status_code == 422, r.text
    assert "41-12" in r.json()["detail"]


def test_consultation_acceptee_en_petite_copropriete(client, token_a, petite):
    r = _ag(client, token_a)
    assert r.status_code == 200, r.text
    assert r.json()["type_ag"] == "consultation_ecrite"


def test_consultation_possible_grace_au_budget(client, token_a, grande, db):
    # 6 logements mais budget moyen < 15 000 € sur 3 exercices consécutifs : petite.
    for annee in (2024, 2025, 2026):
        ex = Exercice(copropriete_id=grande.id, annee=annee)
        db.add(ex)
        db.flush()
        db.add(BudgetLine(exercice_id=ex.id, libelle="Charges", montant=Decimal("9000")))
    db.commit()
    assert _ag(client, token_a).status_code == 200


def test_ag_classique_toujours_possible(client, token_a, grande):
    assert _ag(client, token_a, "annuelle").status_code == 200
    assert _ag(client, token_a, "extraordinaire").status_code == 200


def test_type_d_ag_inconnu_refuse(client, token_a, petite):
    assert _ag(client, token_a, "visio").status_code == 422


def test_transformer_une_ag_en_consultation_hors_petite_refuse(client, token_a, grande):
    ag = _ag(client, token_a, "annuelle").json()
    r = client.put(f"/api/ag/{ag['id']}", json={"date": DATE, "type_ag": "consultation_ecrite",
                                                "rappel_jours": 0}, headers=auth(token_a))
    assert r.status_code == 422, r.text


def test_transformer_une_ag_dont_une_resolution_n_est_pas_a_l_unanimite(client, token_a, petite):
    ag = _ag(client, token_a, "annuelle").json()
    assert _resolution(client, token_a, ag["id"], majorite="art24").status_code == 200
    r = client.put(f"/api/ag/{ag['id']}", json={"date": DATE, "type_ag": "consultation_ecrite",
                                                "rappel_jours": 0}, headers=auth(token_a))
    assert r.status_code == 422, r.text


def test_consultation_existante_reste_modifiable(client, token_a, grande, db):
    # Créée avant ce contrôle, dans une copropriété qui n'est pas « petite » : on ne bloque
    # pas sa modification (notes, statut), seulement l'ajout de résolutions non conformes.
    ag = AG(copropriete_id=grande.id, date=date(2026, 12, 10),
            type_ag="consultation_ecrite", rappel_jours=0)
    db.add(ag)
    db.commit()
    r = client.put(f"/api/ag/{ag.id}", json={"date": DATE, "type_ag": "consultation_ecrite",
                                            "statut": "terminee", "rappel_jours": 0}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert _resolution(client, token_a, ag.id, majorite="art24").status_code == 422


# ---------------------------------------------------------------- unanimité imposée
def test_resolution_a_l_unanimite_acceptee(client, token_a, petite):
    ag = _ag(client, token_a).json()
    r = _resolution(client, token_a, ag["id"])
    assert r.status_code == 200, r.text
    assert r.json()["majorite"] == "unanimite" and r.json()["nature"] == "autre"


@pytest.mark.parametrize("majorite", ["art24", "art25", "art26"])
def test_autre_majorite_refusee_en_consultation(client, token_a, petite, majorite):
    ag = _ag(client, token_a).json()
    r = _resolution(client, token_a, ag["id"], majorite=majorite)
    assert r.status_code == 422, r.text
    assert "unanimité" in r.json()["detail"]


def test_modifier_la_majorite_en_consultation_refuse(client, token_a, petite):
    ag = _ag(client, token_a).json()
    res = _resolution(client, token_a, ag["id"]).json()
    r = client.put(f"/api/resolutions/{res['id']}", json={"numero": 1, "libelle": "x", "majorite": "art25"},
                   headers=auth(token_a))
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------- budget et comptes exclus
@pytest.mark.parametrize("nature", ["budget", "approbation_comptes"])
def test_budget_et_comptes_exclus_de_la_consultation(client, token_a, petite, nature):
    ag = _ag(client, token_a).json()
    r = _resolution(client, token_a, ag["id"], nature=nature)
    assert r.status_code == 422, r.text
    assert "assemblée générale" in r.json()["detail"]


@pytest.mark.parametrize("nature", ["budget", "approbation_comptes"])
def test_budget_et_comptes_possibles_en_ag(client, token_a, petite, nature, db):
    ag = _ag(client, token_a, "annuelle").json()
    # Tâche 21 : une approbation des comptes désigne l'exercice approuvé.
    ex = Exercice(copropriete_id=petite.id, annee=2025, cloture=True)
    db.add(ex)
    db.commit()
    exercice_id = ex.id if nature == "approbation_comptes" else None
    r = _resolution(client, token_a, ag["id"], majorite="art24", nature=nature, exercice_id=exercice_id)
    assert r.status_code == 200, r.text
    assert r.json()["nature"] == nature


def test_nature_inconnue_refusee(client, token_a, petite):
    ag = _ag(client, token_a, "annuelle").json()
    assert _resolution(client, token_a, ag["id"], majorite="art24", nature="divers").status_code == 422


# ---------------------------------------------------------------- calcul : unanimité de TOUS
def test_unanimite_de_tous_les_coproprietaires(client, token_a, petite, db):
    ag = _ag(client, token_a).json()
    res = _resolution(client, token_a, ag["id"]).json()
    lots = db.query(Lot).filter(Lot.copropriete_id == petite.id).order_by(Lot.id).all()
    for lot in lots[:2]:
        client.post(f"/api/resolutions/{res['id']}/votes", json={"lot_id": lot.id, "voix": "pour"},
                    headers=auth(token_a))
    # un copropriétaire n'a pas répondu : pas d'unanimité
    r = client.post(f"/api/resolutions/{res['id']}/calculer", headers=auth(token_a))
    assert r.json()["statut"] == "rejetee"
    client.post(f"/api/resolutions/{res['id']}/votes", json={"lot_id": lots[2].id, "voix": "pour"},
                headers=auth(token_a))
    r = client.post(f"/api/resolutions/{res['id']}/calculer", headers=auth(token_a))
    assert r.json()["statut"] == "adoptee"
