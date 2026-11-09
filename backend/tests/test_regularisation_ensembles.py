"""Régularisation des charges et lots non séparables (tâche 37) : une ligne par ensemble.

Demande de Fred : « quand je clôture une année, j'ai la régularisation pour chaque lot ; or si j'ai
regroupé les lots, je ne devrais voir que les groupes de lots ».

Règles retenues :
- l'aperçu donne une ligne par ensemble (lot principal + annexes) : provisions, charges réelles et
  écart additionnés, au nom « Lot 1 (avec lot 2) » ; un lot sans rattachement garde sa ligne ;
- l'appel « Régularisation des charges » porte une seule part par ensemble, sur le lot principal,
  du montant de l'écart de l'ensemble ; un ensemble dont l'écart total est nul n'a pas de part ;
- le calcul des charges réelles ne change pas (tantièmes de chaque lot, dépenses imputées à un lot).
"""
from datetime import date, timedelta

from app.models.appel import AppelFonds
from app.models.lot import Lot
from tests.conftest import auth
from tests.test_regularisation_charges import AUJOURDHUI, _exercice, _url


def _rattacher(db, annexe, principal):
    annexe.proprietaire_id = principal.proprietaire_id
    annexe.lot_principal_id = principal.id
    db.commit()


def test_apercu_par_ensemble(client, db, copro_a, syndic_a, token_a):
    ex, l1, l2 = _exercice(db, copro_a)
    _rattacher(db, l2, l1)
    d = client.get(_url(ex), headers=auth(token_a)).json()
    # Lot 1 : 600 / 540 / −60 ; lot 2 : 400 / 410 / +10 → ensemble : 1000 / 950 / −50.
    [l] = d["lignes"]
    assert (l["lot_id"], l["libelle"], l["annexes"]) == (l1.id, "Lot 1 (avec lot 2)", ["2"])
    assert (l["provisions"], l["charges_reelles"], l["ecart"]) == (1000, 950, -50)
    assert (d["total_provisions"], d["total_charges_reelles"], d["total_ecart"]) == (1000, 950, -50)


def test_sans_rattachement_une_ligne_par_lot(client, db, copro_a, syndic_a, token_a):
    ex, l1, l2 = _exercice(db, copro_a)
    lignes = {l["lot_numero"]: l for l in client.get(_url(ex), headers=auth(token_a)).json()["lignes"]}
    assert set(lignes) == {"1", "2"}
    assert (lignes["1"]["libelle"], lignes["1"]["annexes"]) == ("Lot 1", [])


def test_appel_une_part_par_ensemble(client, db, copro_a, syndic_a, token_a):
    ex, l1, l2 = _exercice(db, copro_a)
    _rattacher(db, l2, l1)
    r = client.post(_url(ex), json={"date_echeance": (AUJOURDHUI + timedelta(days=30)).isoformat()},
                    headers=auth(token_a))
    assert r.status_code == 200, r.text
    appel = db.get(AppelFonds, r.json()["appel_id"])
    assert [(p.lot_id, float(p.montant_charges)) for p in appel.parts] == [(l1.id, -50)]
    assert float(appel.montant_total) == -50


def test_ecart_nul_sur_l_ensemble(client, db, copro_a, syndic_a, token_a):
    """Lot 1 −60 et une annexe à +60 : l'ensemble est juste, rien à régulariser pour lui."""
    ex, l1, l2 = _exercice(db, copro_a)
    cave = Lot(copropriete_id=copro_a.id, numero="12", tantiemes=0, proprietaire_id=l1.proprietaire_id,
               lot_principal_id=l1.id)
    db.add(cave)
    db.flush()
    from app.models.mouvement import Mouvement
    db.add(Mouvement(copropriete_id=copro_a.id, exercice_id=ex.id, date=date(ex.annee, 7, 1), libelle="Cave",
                     type="depense", categorie="entretien", montant=60, lot_id=cave.id))
    db.commit()
    d = client.get(_url(ex), headers=auth(token_a)).json()
    lignes = {l["lot_numero"]: l for l in d["lignes"]}
    assert lignes["1"]["ecart"] == 0 and lignes["1"]["annexes"] == ["12"]
    r = client.post(_url(ex), json={"date_echeance": (AUJOURDHUI + timedelta(days=30)).isoformat()},
                    headers=auth(token_a))
    appel = db.get(AppelFonds, r.json()["appel_id"])
    assert [p.lot_id for p in appel.parts] == [l2.id]          # seul le lot 2 (+10) est appelé
