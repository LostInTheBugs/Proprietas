"""Paiement d'un copropriétaire pour tous ses lots (un virement, plusieurs lots).

Règles retenues :
- répartition proposée : les sommes restant dues sur l'ensemble des lots du copropriétaire sont
  soldées de la plus ancienne échéance à la plus récente (même règle FIFO que le décompte) ;
- un excédent (avance) va au lot qui a le plus de tantièmes ;
- le syndic peut corriger la répartition ; la somme des parts doit égaler le montant reçu ;
- l'enregistrement crée un encaissement par lot (libellé commun suivi du lot), dans l'exercice de
  l'année de la date (créé s'il manque), et l'inscrit au journal d'audit ;
- seuls les lots dont il est propriétaire sont acceptés ; réservé au syndic ; isolation par copropriété.
"""
from datetime import date

from app.models.appel import AppelFonds, AppelLot
from app.models.audit import AuditLog
from app.models.exercice import Exercice
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.core.security import create_access_token
from tests.conftest import _make_membre, auth

Y = date.today().year


def _situation(db, copro):
    """Martin possède les lots 1 (300 millièmes) et 3 (500) ; Petit le lot 2.
    Appel T1 (15/01) : lot 1 = 300, lot 3 = 100. Appel T2 (15/04) : lot 1 = 50, lot 3 = 200."""
    martin = _make_membre(db, "martin@test.fr", copro)
    petit = _make_membre(db, "petit@test.fr", copro)
    l1 = Lot(copropriete_id=copro.id, numero="1", tantiemes=300, proprietaire_id=martin.id)
    l2 = Lot(copropriete_id=copro.id, numero="2", tantiemes=200, proprietaire_id=petit.id)
    l3 = Lot(copropriete_id=copro.id, numero="3", tantiemes=500, proprietaire_id=martin.id)
    db.add_all([l1, l2, l3])
    ex = Exercice(copropriete_id=copro.id, annee=Y, cloture=False)
    db.add(ex)
    db.flush()
    for libelle, echeance, parts in (("T1", date(Y, 1, 15), {l1: 300, l3: 100}),
                                     ("T2", date(Y, 4, 15), {l3: 200, l1: 50})):
        a = AppelFonds(exercice_id=ex.id, libelle=libelle, date_emission=echeance, date_echeance=echeance,
                       montant_total=sum(parts.values()))
        db.add(a)
        db.flush()
        for lot, montant in parts.items():
            db.add(AppelLot(appel_id=a.id, lot_id=lot.id, montant_charges=montant, montant_fonds_travaux=0))
    db.commit()
    return martin, petit, l1, l2, l3


def _apercu(client, token, proprietaire_id, montant):
    return client.get(f"/api/paiements/repartition?proprietaire_id={proprietaire_id}&montant={montant}",
                      headers=auth(token))


def _soldes(client, token):
    return {s["lot"]["numero"]: s["solde"] for s in client.get("/api/lots/soldes", headers=auth(token)).json()}


def test_repartition_de_la_plus_ancienne_echeance_a_la_plus_recente(client, db, copro_a, syndic_a, token_a):
    martin, _, l1, _, l3 = _situation(db, copro_a)
    r = _apercu(client, token_a, martin.id, 500)
    assert r.status_code == 200, r.text
    d = {l["lot_numero"]: l for l in r.json()["lots"]}
    # T1 (15/01) : lot 1 300 + lot 3 100 = 400 ; T2 (15/04), dans l'ordre des lots : lot 1 50, lot 3 50.
    assert (d["1"]["du"], d["1"]["propose"]) == (350, 350)
    assert (d["3"]["du"], d["3"]["propose"]) == (300, 150)
    assert "2" not in d
    assert r.json()["excedent"] == 0


def test_excedent_au_lot_principal(client, db, copro_a, syndic_a, token_a):
    martin, *_ = _situation(db, copro_a)
    d = _apercu(client, token_a, martin.id, 700).json()
    parts = {l["lot_numero"]: l["propose"] for l in d["lots"]}
    # Dû total 650 ; excédent de 50 au lot 3 (500 millièmes).
    assert parts == {"1": 350, "3": 350} and d["excedent"] == 50


def test_enregistrer_un_paiement(client, db, copro_a, syndic_a, token_a):
    martin, _, l1, _, l3 = _situation(db, copro_a)
    corps = {"proprietaire_id": martin.id, "date": f"{Y}-05-02", "montant": 500, "libelle": "Virement Martin",
             "repartition": [{"lot_id": l1.id, "montant": 300}, {"lot_id": l3.id, "montant": 200}]}
    r = client.post("/api/paiements", json=corps, headers=auth(token_a))
    assert r.status_code == 200, r.text
    m = db.query(Mouvement).order_by(Mouvement.lot_id).all()
    assert [(x.lot_id, float(x.montant), x.type, x.libelle) for x in m] == [
        (l1.id, 300, "encaissement", "Virement Martin — lot 1"), (l3.id, 200, "encaissement", "Virement Martin — lot 3")]
    assert all(x.exercice.annee == Y and x.date == date(Y, 5, 2) for x in m)
    assert _soldes(client, token_a) == {"1": 50, "2": 0, "3": 100}
    assert db.query(AuditLog).filter(AuditLog.action == "paiement_enregistre").count() == 1


def test_une_part_nulle_n_est_pas_enregistree(client, db, copro_a, syndic_a, token_a):
    martin, _, l1, _, l3 = _situation(db, copro_a)
    corps = {"proprietaire_id": martin.id, "date": f"{Y}-05-02", "montant": 100, "libelle": "Virement",
             "repartition": [{"lot_id": l1.id, "montant": 100}, {"lot_id": l3.id, "montant": 0}]}
    assert client.post("/api/paiements", json=corps, headers=auth(token_a)).status_code == 200
    assert db.query(Mouvement).count() == 1


def test_exercice_cree_s_il_manque(client, db, copro_a, syndic_a, token_a):
    martin, _, l1, _, _ = _situation(db, copro_a)
    corps = {"proprietaire_id": martin.id, "date": f"{Y - 1}-12-30", "montant": 10, "libelle": "Virement",
             "repartition": [{"lot_id": l1.id, "montant": 10}]}
    assert client.post("/api/paiements", json=corps, headers=auth(token_a)).status_code == 200
    assert db.query(Mouvement).one().exercice.annee == Y - 1


def test_somme_differente_du_montant_refusee(client, db, copro_a, syndic_a, token_a):
    martin, _, l1, _, l3 = _situation(db, copro_a)
    corps = {"proprietaire_id": martin.id, "date": f"{Y}-05-02", "montant": 500, "libelle": "Virement",
             "repartition": [{"lot_id": l1.id, "montant": 300}, {"lot_id": l3.id, "montant": 150}]}
    r = client.post("/api/paiements", json=corps, headers=auth(token_a))
    assert r.status_code == 422 and "450" in r.json()["detail"]
    assert db.query(Mouvement).count() == 0


def test_lot_d_un_autre_proprietaire_refuse(client, db, copro_a, syndic_a, token_a):
    martin, _, l1, l2, _ = _situation(db, copro_a)
    corps = {"proprietaire_id": martin.id, "date": f"{Y}-05-02", "montant": 100, "libelle": "Virement",
             "repartition": [{"lot_id": l2.id, "montant": 100}]}
    assert client.post("/api/paiements", json=corps, headers=auth(token_a)).status_code == 422
    assert db.query(Mouvement).count() == 0


def test_montant_positif(client, db, copro_a, syndic_a, token_a):
    martin, _, l1, _, _ = _situation(db, copro_a)
    corps = {"proprietaire_id": martin.id, "date": f"{Y}-05-02", "montant": 0, "libelle": "Virement",
             "repartition": [{"lot_id": l1.id, "montant": 0}]}
    assert client.post("/api/paiements", json=corps, headers=auth(token_a)).status_code == 422
    assert _apercu(client, token_a, martin.id, -5).status_code == 422


def test_reserve_au_syndic(client, db, copro_a, syndic_a, token_a):
    martin, *_ = _situation(db, copro_a)
    tok = create_access_token(martin.id, copro_a.id)
    assert _apercu(client, tok, martin.id, 100).status_code == 403


def test_isolation_entre_coproprietes(client, db, copro_a, copro_b, syndic_a, syndic_b, token_b):
    martin, _, l1, _, _ = _situation(db, copro_a)
    assert _apercu(client, token_b, martin.id, 100).status_code == 422
    corps = {"proprietaire_id": martin.id, "date": f"{Y}-05-02", "montant": 100, "libelle": "Virement",
             "repartition": [{"lot_id": l1.id, "montant": 100}]}
    assert client.post("/api/paiements", json=corps, headers=auth(token_b)).status_code == 422
