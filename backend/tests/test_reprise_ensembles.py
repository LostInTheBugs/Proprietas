"""Historique (reprise) et lots non séparables (tâche 37) : les contrôles se font par ensemble.

Cas : Martin a le lot 1 (appartement) et la cave 12, rattachée au lot 1 ; il paie l'ensemble par un
seul virement sur le lot 1. Lot par lot, le contrôle verrait −30 € sur le lot 1 et +30 € sur la cave
alors que l'ensemble est juste : la validation serait refusée à tort.

Règles retenues :
- base + appels − encaissements est comparé à l'état saisi PAR ENSEMBLE (lot principal et ses
  annexes) ; un lot sans rattachement reste contrôlé seul ;
- une ligne de contrôle par ensemble, au nom du lot principal, avec ses annexes ; les montants saisis
  sur une annexe comptent dans l'ensemble ;
- le message d'écart nomme l'ensemble.
"""
from datetime import date

from app.models.appel import AppelFonds, AppelLot
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from tests.conftest import _make_membre, auth
from tests.test_reprise_historique import B, B0, Y, _base, _creer, _exercice, _ligne, _valider, URL


def _copro(db, copro, rattacher=True):
    martin = _make_membre(db, "martin@test.fr", copro)
    petit = _make_membre(db, "petit@test.fr", copro)
    l1 = Lot(copropriete_id=copro.id, numero="1", tantiemes=500, proprietaire_id=martin.id)
    l2 = Lot(copropriete_id=copro.id, numero="2", tantiemes=450, proprietaire_id=petit.id)
    db.add_all([l1, l2])
    db.flush()
    cave = Lot(copropriete_id=copro.id, numero="12", tantiemes=50, proprietaire_id=martin.id,
               lot_principal_id=l1.id if rattacher else None)
    db.add(cave)
    db.commit()
    return l1, cave, l2


def _annee(db, copro, l1, cave, l2):
    """Appel de l'année Y : lot 1 = 300, cave = 30, lot 2 = 200. Martin paie 430 sur le lot 1 (son
    ensemble, plus les 100 dus au 31/12/Y-1) ; Petit paie 250 sur le lot 2."""
    ex = _exercice(db, copro, Y)
    a = AppelFonds(exercice_id=ex.id, libelle=f"Provisions {Y}", date_emission=date(Y, 3, 1),
                   date_echeance=date(Y, 3, 15), montant_total=530)
    db.add(a)
    db.flush()
    db.add_all([AppelLot(appel_id=a.id, lot_id=l1.id, montant_charges=300, montant_fonds_travaux=0),
                AppelLot(appel_id=a.id, lot_id=cave.id, montant_charges=30, montant_fonds_travaux=0),
                AppelLot(appel_id=a.id, lot_id=l2.id, montant_charges=200, montant_fonds_travaux=0)])
    for lot, montant in ((l1, 430), (l2, 250)):
        db.add(Mouvement(copropriete_id=copro.id, exercice_id=ex.id, date=date(Y, 3, 10), libelle="Virement",
                         type="encaissement", categorie="charges", montant=montant, lot_id=lot.id))
    db.commit()


def test_controle_par_ensemble(client, db, copro_a, syndic_a, token_a):
    l1, cave, l2 = _copro(db, copro_a)
    _base(client, token_a, B0, [_ligne(l1, Y - 1, 100), _ligne(l2, Y - 1, 50)])
    _annee(db, copro_a, l1, cave, l2)
    # Au 31/12/Y : l'ensemble de Martin est soldé (100 + 330 − 430), Petit aussi (50 + 200 − 250).
    r = _creer(client, token_a, B, [_ligne(l1, Y, 0), _ligne(l2, Y, 0)])
    etat_id = r.json()["id"]
    [c] = client.get(f"{URL}/{etat_id}", headers=auth(token_a)).json()["controles"]
    assert c["ok"] is True, c
    lignes = {l["lot_numero"]: l for l in c["lignes"]}
    assert set(lignes) == {"1", "2"}                          # la cave n'a pas de ligne à elle
    assert lignes["1"]["libelle"] == "Lot 1 (avec lot 12)" and lignes["1"]["annexes"] == ["12"]
    assert (lignes["1"]["attendu"], lignes["1"]["calcule"], lignes["1"]["ecart"]) == (0, 0, 0)
    assert lignes["2"]["libelle"] == "Lot 2" and lignes["2"]["annexes"] == []
    assert _valider(client, token_a, etat_id).status_code == 200


def test_sans_rattachement_controle_lot_par_lot(client, db, copro_a, syndic_a, token_a):
    l1, cave, l2 = _copro(db, copro_a, rattacher=False)
    _base(client, token_a, B0, [_ligne(l1, Y - 1, 100), _ligne(l2, Y - 1, 50)])
    _annee(db, copro_a, l1, cave, l2)
    r = _creer(client, token_a, B, [_ligne(l1, Y, 0), _ligne(l2, Y, 0)])
    v = _valider(client, token_a, r.json()["id"])
    assert v.status_code == 422
    assert "lot 1 : +30,00 €" in v.json()["detail"] and "lot 12 : -30,00 €" in v.json()["detail"]


def test_montant_saisi_sur_l_annexe_compte_dans_l_ensemble(client, db, copro_a, syndic_a, token_a):
    l1, cave, l2 = _copro(db, copro_a)
    # Base : les 100 € de Martin saisis sur la cave (relevé de l'ancien syndic par lot).
    _base(client, token_a, B0, [_ligne(cave, Y - 1, 100), _ligne(l2, Y - 1, 50)])
    _annee(db, copro_a, l1, cave, l2)
    r = _creer(client, token_a, B, [_ligne(l1, Y, 0), _ligne(l2, Y, 0)])
    assert _valider(client, token_a, r.json()["id"]).status_code == 200


def test_ecart_nomme_l_ensemble(client, db, copro_a, syndic_a, token_a):
    l1, cave, l2 = _copro(db, copro_a)
    _base(client, token_a, B0, [_ligne(l1, Y - 1, 100), _ligne(l2, Y - 1, 50)])
    _annee(db, copro_a, l1, cave, l2)
    r = _creer(client, token_a, B, [_ligne(l1, Y, 20), _ligne(l2, Y, 0)])
    v = _valider(client, token_a, r.json()["id"])
    assert v.status_code == 422
    assert "Lot 1 (avec lot 12) : +20,00 €" in v.json()["detail"]
