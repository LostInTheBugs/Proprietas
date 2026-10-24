"""Régime « petite copropriété » : loi n° 65-557, art. 41-8.

Une copropriété relève du régime simplifié si :
- elle compte au plus 5 lots À USAGE DE LOGEMENTS, DE BUREAUX OU DE COMMERCES
  (les caves, parkings et autres annexes ne comptent pas) ;
- OU son budget prévisionnel moyen sur 3 EXERCICES CONSÉCUTIFS est inférieur à 15 000 €.

Erreurs corrigées :
- tous les lots étaient comptés (caves et parkings compris) ;
- la moyenne était faite sur 1 ou 2 exercices s'il en manquait, et valait 0 sans budget,
  ce qui classait à tort en « petite copropriété » toute copropriété sans historique.
Prudence : un lot « autre » compte comme lot principal (mieux vaut appliquer à tort le
régime général que le régime simplifié, qui allège les règles).
"""
from decimal import Decimal

import pytest

from app.models.exercice import BudgetLine, Exercice
from app.models.lot import Lot
from app.services import country_rules
from tests.conftest import auth


def _lots(db, copro, *types):
    db.add_all([Lot(copropriete_id=copro.id, numero=str(i + 1), type=t, tantiemes=100)
                for i, t in enumerate(types)])
    db.commit()


def _budgets(db, copro, par_annee):
    for annee, montant in par_annee.items():
        ex = Exercice(copropriete_id=copro.id, annee=annee)
        db.add(ex)
        db.flush()
        if montant:
            db.add(BudgetLine(exercice_id=ex.id, libelle="Charges", montant=Decimal(str(montant))))
    db.commit()


def _recap(client, token_a):
    r = client.get("/api/recap", headers=auth(token_a))
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- règles pures
def test_seuls_logements_bureaux_commerces_comptent():
    class L:
        def __init__(self, t): self.type = t
    lots = [L(t) for t in ("appartement", "maison", "bureau", "commerce", "autre",
                           "cave", "parking", "annexe")]
    assert country_rules.nb_lots_principaux(lots) == 5


@pytest.mark.parametrize("budgets,attendu", [
    ({2024: 10000, 2025: 12000, 2026: 14000}, Decimal("12000")),
    ({2023: 90000, 2024: 10000, 2025: 12000, 2026: 14000}, Decimal("12000")),  # les 3 derniers
    ({2025: 5000, 2026: 5000}, None),                                          # moins de 3
    ({2023: 5000, 2025: 5000, 2026: 5000}, None),                              # pas consécutifs
    ({}, None),
])
def test_budget_moyen_sur_3_exercices_consecutifs(budgets, attendu):
    assert country_rules.budget_moyen_3_exercices({a: Decimal(m) for a, m in budgets.items()}) == attendu


# ---------------------------------------------------------------- API /recap
def test_caves_et_parkings_ne_comptent_pas(client, token_a, db, copro_a):
    # 7 lots dont 3 caves, budget élevé : 4 lots principaux → petite copropriété.
    _lots(db, copro_a, "appartement", "appartement", "appartement", "commerce", "cave", "cave", "parking")
    _budgets(db, copro_a, {2024: 30000, 2025: 30000, 2026: 30000})
    recap = _recap(client, token_a)
    assert recap["nb_lots"] == 7 and recap["nb_lots_principaux"] == 4
    assert recap["regime_petite_copro"] is True


def test_sans_budget_le_critere_du_budget_n_est_pas_rempli(client, token_a, db, copro_a):
    # 6 logements, aucun exercice : AVANT, budget moyen = 0 → « petite » à tort.
    _lots(db, copro_a, *["appartement"] * 6)
    recap = _recap(client, token_a)
    assert recap["budget_moyen_3_exercices"] is None
    assert recap["regime_petite_copro"] is False


def test_moins_de_3_exercices_budgetes(client, token_a, db, copro_a):
    _lots(db, copro_a, *["appartement"] * 6)
    _budgets(db, copro_a, {2025: 5000, 2026: 5000, 2027: 0})     # 2027 : exercice sans budget
    recap = _recap(client, token_a)
    assert recap["budget_moyen_3_exercices"] is None
    assert recap["regime_petite_copro"] is False


def test_budget_moyen_inferieur_a_15000_sur_3_exercices(client, token_a, db, copro_a):
    _lots(db, copro_a, *["appartement"] * 8)
    _budgets(db, copro_a, {2024: 14000, 2025: 15000, 2026: 15500})
    recap = _recap(client, token_a)
    assert recap["budget_moyen_3_exercices"] == 14833.33
    assert recap["regime_petite_copro"] is True


def test_budget_moyen_egal_a_15000_n_est_pas_inferieur(client, token_a, db, copro_a):
    _lots(db, copro_a, *["appartement"] * 8)
    _budgets(db, copro_a, {2024: 15000, 2025: 15000, 2026: 15000})
    assert _recap(client, token_a)["regime_petite_copro"] is False


def test_lot_autre_compte_par_prudence(client, token_a, db, copro_a):
    _lots(db, copro_a, *["appartement"] * 5, "autre")
    recap = _recap(client, token_a)
    assert recap["nb_lots_principaux"] == 6 and recap["regime_petite_copro"] is False


# ---------------------------------------------------------------- saisie du type de lot
@pytest.mark.parametrize("t", ["appartement", "maison", "bureau", "commerce", "cave", "parking", "annexe", "autre"])
def test_types_de_lot_acceptes(client, token_a, t):
    r = client.post("/api/lots", json={"numero": "1", "type": t, "tantiemes": 100}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert r.json()["type"] == t


def test_type_de_lot_inconnu_refuse(client, token_a):
    r = client.post("/api/lots", json={"numero": "1", "type": "garage", "tantiemes": 100}, headers=auth(token_a))
    assert r.status_code == 422


def test_lot_ancien_au_type_inconnu_reste_lisible(client, token_a, db, copro_a):
    _lots(db, copro_a, "garage")                  # donnée saisie avant le contrôle
    r = client.get("/api/lots", headers=auth(token_a))
    assert r.status_code == 200 and r.json()[0]["type"] == "garage"
