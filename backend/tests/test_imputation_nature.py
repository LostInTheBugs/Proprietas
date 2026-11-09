"""Imputation des encaissements par nature : charges / fonds de travaux.

Règles retenues :
- un encaissement de catégorie « fonds de travaux » (ou « travaux ») ne paie que la part fonds de
  travaux des appels, de la plus ancienne à la plus récente ; son reste est une avance travaux,
  jamais utilisée pour des charges ;
- les autres encaissements (charges…) et les crédits paient ensuite ce qui reste dû, appel par appel,
  charges puis fonds de travaux ; leur reste est une avance sur charges ;
- sans encaissement « travaux », rien ne change (imputation unique, de la plus ancienne échéance) ;
- le dossier de recouvrement donne le dû et l'avance pour chaque nature ;
- le paiement d'un copropriétaire peut être ventilé par lot entre charges et travaux : un
  encaissement par nature et par lot.
"""
from datetime import date

from app.models.appel import AppelFonds, AppelLot
from app.models.exercice import Exercice
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from tests.conftest import _make_membre, auth

Y = date.today().year


def _lot(db, copro):
    """Lot 1 : appels T1 (15/01) et T2 (15/04), chacun 400 € de charges + 20 € de fonds de travaux."""
    p = _make_membre(db, "martin@test.fr", copro)
    lot = Lot(copropriete_id=copro.id, numero="1", tantiemes=1000, proprietaire_id=p.id)
    db.add(lot)
    ex = Exercice(copropriete_id=copro.id, annee=Y, cloture=False)
    db.add(ex)
    db.flush()
    for libelle, echeance in (("T1", date(Y, 1, 15)), ("T2", date(Y, 4, 15))):
        a = AppelFonds(exercice_id=ex.id, libelle=libelle, date_emission=echeance, date_echeance=echeance,
                       montant_total=420, inclut_fonds_travaux=True, fonds_travaux_montant=20)
        db.add(a)
        db.flush()
        db.add(AppelLot(appel_id=a.id, lot_id=lot.id, montant_charges=400, montant_fonds_travaux=20))
    db.commit()
    return p, lot, ex


def _encaisser(db, copro, ex, lot, montant, categorie, jour=None):
    db.add(Mouvement(copropriete_id=copro.id, exercice_id=ex.id, date=jour or date(Y, 2, 1), libelle="Virement",
                     type="encaissement", categorie=categorie, montant=montant, lot_id=lot.id))
    db.commit()


def _dossier(client, token, lot):
    r = client.get(f"/api/recouvrement/lot/{lot.id}", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def test_paiement_travaux_reserve_au_fonds(client, db, copro_a, syndic_a, token_a):
    _, lot, ex = _lot(db, copro_a)
    _encaisser(db, copro_a, ex, lot, 40, "fonds_travaux")
    d = _dossier(client, token_a, lot)
    assert [(l["restant_du_charges"], l["restant_du_fonds"]) for l in d["decompte"]] == [(400, 0), (400, 0)]
    assert (d["du_charges"], d["du_travaux"], d["avance_travaux"]) == (800, 0, 0)


def test_avance_travaux_jamais_utilisee_pour_des_charges(client, db, copro_a, syndic_a, token_a):
    _, lot, ex = _lot(db, copro_a)
    _encaisser(db, copro_a, ex, lot, 100, "fonds_travaux")
    d = _dossier(client, token_a, lot)
    assert (d["du_charges"], d["du_travaux"], d["avance_travaux"], d["avance_charges"]) == (800, 0, 60, 0)
    assert d["solde"] == 800


def test_avance_sur_charges(client, db, copro_a, syndic_a, token_a):
    _, lot, ex = _lot(db, copro_a)
    _encaisser(db, copro_a, ex, lot, 40, "fonds_travaux")
    _encaisser(db, copro_a, ex, lot, 900, "charges")
    d = _dossier(client, token_a, lot)
    assert (d["du_charges"], d["du_travaux"], d["avance_charges"], d["avance_travaux"]) == (0, 0, 100, 0)
    assert d["solde"] == 0


def test_sans_paiement_travaux_rien_ne_change(client, db, copro_a, syndic_a, token_a):
    _, lot, ex = _lot(db, copro_a)
    _encaisser(db, copro_a, ex, lot, 500, "charges")
    d = _dossier(client, token_a, lot)
    # T1 soldé en entier (420), puis 80 sur les charges de T2.
    assert [l["restant_du"] for l in d["decompte"]] == [0, 340]
    assert [(l["restant_du_charges"], l["restant_du_fonds"]) for l in d["decompte"]] == [(0, 0), (320, 20)]
    assert d["solde"] == 340


def test_paiements_travaux_puis_generaux(client, db, copro_a, syndic_a, token_a):
    _, lot, ex = _lot(db, copro_a)
    _encaisser(db, copro_a, ex, lot, 20, "fonds_travaux")
    _encaisser(db, copro_a, ex, lot, 420, "charges")
    d = _dossier(client, token_a, lot)
    # Fonds T1 par le paiement travaux ; charges T1 (400) puis 20 sur les charges de T2.
    assert [(l["restant_du_charges"], l["restant_du_fonds"]) for l in d["decompte"]] == [(0, 0), (380, 20)]


def test_proposition_par_nature(client, db, copro_a, syndic_a, token_a):
    p, lot, _ = _lot(db, copro_a)
    r = client.get(f"/api/paiements/repartition?proprietaire_id={p.id}&montant=440", headers=auth(token_a))
    assert r.status_code == 200, r.text
    [l] = r.json()["lots"]
    # T1 : charges 400 et fonds 20 ; puis 20 sur les charges de T2.
    assert (l["propose_charges"], l["propose_travaux"], l["propose"]) == (420, 20, 440)


def test_excedent_en_avance_sur_charges(client, db, copro_a, syndic_a, token_a):
    p, lot, _ = _lot(db, copro_a)
    [l] = client.get(f"/api/paiements/repartition?proprietaire_id={p.id}&montant=900",
                     headers=auth(token_a)).json()["lots"]
    assert (l["propose_charges"], l["propose_travaux"]) == (860, 40)


def test_enregistrer_un_paiement_ventile(client, db, copro_a, syndic_a, token_a):
    p, lot, _ = _lot(db, copro_a)
    corps = {"proprietaire_id": p.id, "date": f"{Y}-02-01", "montant": 600, "libelle": "Virement",
             "repartition": [{"lot_id": lot.id, "montant": 400, "montant_travaux": 200}]}
    r = client.post("/api/paiements", json=corps, headers=auth(token_a))
    assert r.status_code == 200, r.text
    m = {x.categorie: (float(x.montant), x.libelle) for x in db.query(Mouvement).all()}
    assert m == {"charges": (400, "Virement — lot 1"), "fonds_travaux": (200, "Virement — lot 1 (travaux)")}
    d = _dossier(client, token_a, lot)
    assert (d["du_charges"], d["du_travaux"], d["avance_travaux"]) == (400, 0, 160)


def test_total_ventile_controle(client, db, copro_a, syndic_a, token_a):
    p, lot, _ = _lot(db, copro_a)
    corps = {"proprietaire_id": p.id, "date": f"{Y}-02-01", "montant": 600, "libelle": "Virement",
             "repartition": [{"lot_id": lot.id, "montant": 400, "montant_travaux": 100}]}
    r = client.post("/api/paiements", json=corps, headers=auth(token_a))
    assert r.status_code == 422 and "500" in r.json()["detail"]
