"""Vente d'un lot (demande de Fred, 20/11/2026).

- les lots de l'ensemble (lot principal et annexes) passent à l'acquéreur ;
- coupure à la date de l'acte (décret 1967, art. 6-2) : appels exigibles jusque-là et paiements reçus
  jusque-là au compte du vendeur ; le décompte de l'acquéreur repart de zéro ;
- solde du vendeur encaissé après la vente (notaire) : à son compte, jamais au-delà de ce qu'il doit ;
- avis de mutation : opposition avant 15 jours ; annulation de la dernière vente sans encaissement.
"""
from datetime import date, timedelta

from app.models.appel import AppelFonds, AppelLot
from app.models.exercice import Exercice
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.services.soldes import totaux_lot
from tests.conftest import _make_membre, auth

A = date.today().year - 1          # l'année dernière : toutes les dates de la vente sont passées


def _immeuble(db, copro):
    paul = _make_membre(db, "paul@exemple.fr", copro)
    anne = _make_membre(db, "anne@exemple.fr", copro)
    l1 = Lot(copropriete_id=copro.id, numero="1", tantiemes=600, proprietaire_id=paul.id, statut_occupation="occupant")
    db.add(l1)
    db.flush()
    l12 = Lot(copropriete_id=copro.id, numero="12", tantiemes=40, proprietaire_id=paul.id, lot_principal_id=l1.id)
    l2 = Lot(copropriete_id=copro.id, numero="2", tantiemes=360)
    db.add_all([l12, l2])
    ex = Exercice(copropriete_id=copro.id, annee=A)
    db.add(ex)
    db.flush()
    for mois in (1, 4, 7, 10):                       # provisions trimestrielles de 300 € (lot 1) et 20 € (lot 12)
        a = AppelFonds(exercice_id=ex.id, libelle=f"Provision {mois}", date_emission=date(A, mois, 1),
                       date_echeance=date(A, mois, 1), montant_total=500)
        db.add(a)
        db.flush()
        db.add_all([AppelLot(appel_id=a.id, lot_id=l1.id, montant_charges=300),
                    AppelLot(appel_id=a.id, lot_id=l12.id, montant_charges=20)])
    db.add(Mouvement(copropriete_id=copro.id, exercice_id=ex.id, date=date(A, 1, 10), libelle="Virement Paul",
                     type="encaissement", categorie="charges", montant=320, lot_id=l1.id))
    db.commit()
    return paul, anne, l1, l12, ex


def _vendre(client, token, lot_id, acquereur_id, **champs):
    corps = {"lot_id": lot_id, "date_acte": f"{A}-05-15", "acquereur_id": acquereur_id,
             "notaire": "Étude Durand, Thionville", **champs}
    return client.post("/api/mutations", json=corps, headers=auth(token))


def test_vente_coupe_le_decompte(client, db, copro_a, syndic_a, token_a):
    paul, anne, l1, l12, ex = _immeuble(db, copro_a)
    avant = totaux_lot(db, l1)["solde"] + totaux_lot(db, l12)["solde"]
    assert avant == 4 * 320 - 320
    r = _vendre(client, token_a, l12.id, anne.id, avis_mutation_le=f"{A}-05-20")      # par l'annexe : tout l'ensemble
    assert r.status_code == 200, r.text
    v = r.json()
    assert (v["lot_id"], v["lots"], v["vendeur_nom"], v["opposition_avant_le"]) == (
        l1.id, "Lot 1 (avec lot 12)", paul.nom_complet or paul.email, f"{A}-06-04")
    # Vendeur : provisions de janvier (payée) et d'avril (due) ; acquéreur : juillet et octobre.
    assert v["compte_vendeur"]["du"] == 320 and v["compte_vendeur"]["solde"] == 320
    db.expire_all()
    assert (db.get(Lot, l1.id).proprietaire_id, db.get(Lot, l12.id).proprietaire_id) == (anne.id, anne.id)
    assert db.get(Lot, l1.id).statut_occupation == ""
    assert totaux_lot(db, db.get(Lot, l1.id))["solde"] == 600 and totaux_lot(db, db.get(Lot, l12.id))["solde"] == 40
    soldes = {s["lot"]["numero"]: s["solde"] for s in client.get("/api/lots/soldes", headers=auth(token_a)).json()}
    assert (soldes["1"], soldes["12"]) == (600, 40)


def test_solde_du_vendeur_encaisse_a_son_compte(client, db, copro_a, syndic_a, token_a):
    paul, anne, l1, l12, ex = _immeuble(db, copro_a)
    mid = _vendre(client, token_a, l1.id, anne.id).json()["id"]
    url = f"/api/mutations/{mid}/encaissement"
    r = client.post(url, json={"date": f"{A}-06-01", "montant": 400}, headers=auth(token_a))
    assert r.status_code == 422 and "320,00 €" in r.json()["detail"]
    assert client.post(url, json={"date": f"{A}-05-01", "montant": 320}, headers=auth(token_a)).status_code == 422
    r = client.post(url, json={"date": f"{A}-06-01", "montant": 320}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert (r.json()["compte_vendeur"]["du"], r.json()["compte_vendeur"]["encaisse_apres_vente"]) == (0, 320)
    db.expire_all()
    m = db.query(Mouvement).filter(Mouvement.mutation_id == mid).one()
    assert (m.lot_id, m.type, m.categorie, m.date) == (l1.id, "encaissement", "charges", date(A, 6, 1))
    assert totaux_lot(db, db.get(Lot, l1.id))["solde"] == 600                     # l'acquéreur n'en profite pas
    # Annulation refusée tant que l'encaissement existe.
    assert client.delete(f"/api/mutations/{mid}", headers=auth(token_a)).status_code == 409


def test_controles(client, db, copro_a, syndic_a, token_a, copro_b, syndic_b):
    paul, anne, l1, l12, ex = _immeuble(db, copro_a)
    etranger = _make_membre(db, "x@ailleurs.fr", copro_b)
    assert _vendre(client, token_a, l1.id, etranger.id).status_code == 422          # pas un compte de la copro
    assert _vendre(client, token_a, l1.id, paul.id).status_code == 422              # déjà propriétaire
    futur = str(date.today() + timedelta(days=3))
    assert _vendre(client, token_a, l1.id, anne.id, date_acte=futur).status_code == 422
    assert _vendre(client, token_a, l1.id, anne.id, notifiee_le=f"{A}-05-01").status_code == 422   # avant la vente
    l2 = db.query(Lot).filter(Lot.numero == "2").one()
    assert _vendre(client, token_a, l2.id, anne.id).status_code == 422              # lot sans propriétaire
    assert _vendre(client, token_a, l1.id, anne.id).status_code == 200
    # Revente : postérieure à la précédente, par le nouveau propriétaire.
    r = _vendre(client, token_a, l1.id, paul.id, date_acte=f"{A}-05-15")
    assert r.status_code == 422
    r = _vendre(client, token_a, l1.id, paul.id, date_acte=f"{A}-09-30")
    assert r.status_code == 200, r.text
    assert r.json()["vendeur_nom"] == (anne.nom_complet or anne.email)
    assert r.json()["compte_vendeur"]["du"] == 320                                  # juillet, dû par Anne
    ventes = client.get("/api/mutations", headers=auth(token_a)).json()
    assert [v["derniere"] for v in ventes] == [True, False]
    # Seule la dernière vente s'annule ; le lot revient au vendeur.
    assert client.delete(f"/api/mutations/{ventes[1]['id']}", headers=auth(token_a)).status_code == 409
    assert client.delete(f"/api/mutations/{ventes[0]['id']}", headers=auth(token_a)).status_code == 200
    db.expire_all()
    assert db.get(Lot, l1.id).proprietaire_id == anne.id


def test_suivi_droits_et_isolation(client, db, copro_a, syndic_a, token_a, token_b):
    paul, anne, l1, l12, ex = _immeuble(db, copro_a)
    mid = _vendre(client, token_a, l1.id, anne.id).json()["id"]
    r = client.put(f"/api/mutations/{mid}", json={"notaire": "Me Martin", "notifiee_le": f"{A}-05-16",
                                                  "avis_mutation_le": f"{A}-05-18", "opposition_le": f"{A}-05-30"},
                   headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert (r.json()["notaire"], r.json()["opposition_avant_le"]) == ("Me Martin", f"{A}-06-02")
    from app.core.security import create_access_token
    t = create_access_token(anne.id, copro_a.id)
    assert client.get("/api/mutations", headers=auth(t)).status_code == 403
    assert client.get("/api/mutations", headers=auth(token_b)).json() == []
    assert client.put(f"/api/mutations/{mid}", json={}, headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/mutations/{mid}", headers=auth(token_b)).status_code == 404
