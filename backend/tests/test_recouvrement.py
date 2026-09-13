"""Recouvrement : décompte FIFO, statuts du dossier, mise en demeure, article 19-2.

Les dates sont construites RELATIVES à aujourd'hui (robuste dans le temps) :
- exercice précédent : année n-1 (clôturé), appel échu ;
- exercice en cours : appel échu partiel + appel à échoir.
"""
from datetime import date, timedelta

from app.models.appel import AppelFonds, AppelLot
from app.models.exercice import Exercice
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.models.personne import Personne
from app.models.recouvrement import ActeRecouvrement
from tests.conftest import _make_membre, auth

AUJOURDHUI = date.today()
ECHU = AUJOURDHUI - timedelta(days=60)
A_ECHOIR = AUJOURDHUI + timedelta(days=60)


def _campagne(db, copro):
    """Lot + propriétaire + 2 exercices + appels + encaissement partiel.

    Attendu : solde 550 ; arriéré échu 400 ; à échoir 150 ; retard depuis l'échéance n-1.
    """
    lot = Lot(copropriete_id=copro.id, numero="1", designation="T2", tantiemes=500)
    db.add(lot)
    db.flush()
    p = Personne(copropriete_id=copro.id, nom="Dupont", prenom="Jean",
                 email="j.dupont@test.fr", adresse="1 rue de la Paix, 75011 Paris")
    db.add(p)
    db.flush()
    lot.proprietaire_id = p.id

    ex_prev = Exercice(copropriete_id=copro.id, annee=AUJOURDHUI.year - 1, cloture=True)
    ex_cur = Exercice(copropriete_id=copro.id, annee=AUJOURDHUI.year, cloture=False)
    db.add_all([ex_prev, ex_cur])
    db.flush()

    a_prev = AppelFonds(exercice_id=ex_prev.id, libelle="Budget {annee}".format(annee=ex_prev.annee),
                        date_emission=ECHU - timedelta(days=400), date_echeance=ECHU - timedelta(days=380),
                        montant_total=300)
    a_echu = AppelFonds(exercice_id=ex_cur.id, libelle="Budget {annee} — 1er appel".format(annee=ex_cur.annee),
                        date_emission=ECHU - timedelta(days=20), date_echeance=ECHU, montant_total=200)
    a_futur = AppelFonds(exercice_id=ex_cur.id, libelle="Budget {annee} — 2e appel".format(annee=ex_cur.annee),
                         date_emission=A_ECHOIR - timedelta(days=20), date_echeance=A_ECHOIR, montant_total=150)
    db.add_all([a_prev, a_echu, a_futur])
    db.flush()
    db.add_all([
        AppelLot(appel_id=a_prev.id, lot_id=lot.id, montant_charges=300, montant_fonds_travaux=0),
        AppelLot(appel_id=a_echu.id, lot_id=lot.id, montant_charges=200, montant_fonds_travaux=0),
        AppelLot(appel_id=a_futur.id, lot_id=lot.id, montant_charges=150, montant_fonds_travaux=0),
    ])
    # Un versement partiel de 100 € (imputé FIFO sur l'appel le plus ancien : 300 → reste 200)
    db.add(Mouvement(copropriete_id=copro.id, exercice_id=ex_prev.id, date=ECHU - timedelta(days=370),
                     libelle="Versement partiel", type="encaissement", montant=100, lot_id=lot.id))
    db.commit()
    return lot, p, a_echu, a_futur


def _md_enregistree(client, token, lot_id, jours_avant=0, mode="lre", montant_md=None):
    d = (AUJOURDHUI - timedelta(days=jours_avant)).isoformat()
    r = client.post(f"/api/recouvrement/lot/{lot_id}/acte",
                    json={"type": "mise_en_demeure", "date_envoi": d, "mode_envoi": mode,
                          "reference": "LRE-123"},
                    headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _lot_avec_impaye_echu(db, copro, numero="2"):
    """Petit lot avec un impayé échu (pour les cas de refus)."""
    lot = Lot(copropriete_id=copro.id, numero=numero, tantiemes=100)
    db.add(lot)
    db.flush()
    ex = Exercice(copropriete_id=copro.id, annee=AUJOURDHUI.year - 1, cloture=True)
    db.add(ex)
    db.flush()
    a = AppelFonds(exercice_id=ex.id, libelle="Appel test", date_emission=ECHU - timedelta(days=10),
                   date_echeance=ECHU, montant_total=50)
    db.add(a)
    db.flush()
    db.add(AppelLot(appel_id=a.id, lot_id=lot.id, montant_charges=50, montant_fonds_travaux=0))
    db.commit()
    return lot


def test_decompte_fifo_et_liste(client, db, copro_a, syndic_a, token_a):
    lot, p, _, _ = _campagne(db, copro_a)
    r = client.get("/api/recouvrement", headers=auth(token_a))
    assert r.status_code == 200, r.text
    d = {e["lot_id"]: e for e in r.json()}[lot.id]
    assert d["solde"] == 550.0
    assert d["statut"] == "en_retard"
    assert d["retard_depuis"] == (ECHU - timedelta(days=380)).isoformat()

    dossier = client.get(f"/api/recouvrement/lot/{lot.id}", headers=auth(token_a)).json()
    restants = [l["restant_du"] for l in dossier["decompte"]]
    assert restants == [200.0, 200.0, 150.0]  # FIFO : le versement s'impute sur l'appel le plus ancien
    assert dossier["arriere_echu"] == 400.0
    assert len(dossier["decompte"]) == 3


def test_mise_en_demeure_pdf_et_acte(client, db, copro_a, syndic_a, token_a):
    lot, p, _, _ = _campagne(db, copro_a)
    r = client.get(f"/api/recouvrement/lot/{lot.id}/mise-en-demeure.pdf", headers=auth(token_a))
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"

    acte = _md_enregistree(client, token_a, lot.id)
    assert acte["type"] == "mise_en_demeure"
    assert acte["montant"] == 400.0  # provisions échues impayées
    assert acte["reference"] == "LRE-123"

    d = {e["lot_id"]: e for e in client.get("/api/recouvrement", headers=auth(token_a)).json()}[lot.id]
    assert d["statut"] == "mise_en_demeure"
    assert d["jours_restants"] == 30


def test_md_sans_provision_echue_refusee(client, db, copro_a, syndic_a, token_a):
    lot = Lot(copropriete_id=copro_a.id, numero="9", tantiemes=100)
    db.add(lot)
    db.commit()
    r = client.get(f"/api/recouvrement/lot/{lot.id}/mise-en-demeure.pdf", headers=auth(token_a))
    assert r.status_code == 400
    r = client.post(f"/api/recouvrement/lot/{lot.id}/acte",
                    json={"type": "mise_en_demeure", "date_envoi": AUJOURDHUI.isoformat(), "mode_envoi": "lre"},
                    headers=auth(token_a))
    assert r.status_code == 400


def test_mode_envoi_requis_pour_md(client, db, copro_a, syndic_a, token_a):
    lot, p, _, _ = _campagne(db, copro_a)
    r = client.post(f"/api/recouvrement/lot/{lot.id}/acte",
                    json={"type": "mise_en_demeure", "date_envoi": AUJOURDHUI.isoformat()},
                    headers=auth(token_a))
    assert r.status_code == 422


def test_article_19_2_apres_30_jours(client, db, copro_a, syndic_a, token_a):
    lot, p, _, _ = _campagne(db, copro_a)
    acte = _md_enregistree(client, token_a, lot.id, jours_avant=31)
    # 19-2 : provisions non échues de l'exercice en cours (150) + restants des exercices
    # précédents (200) → 350 ; l'échu courant (200) est déjà exigible (hors 19-2).
    r = client.get(f"/api/recouvrement/lot/{lot.id}/19-2", headers=auth(token_a))
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["total"] == 350.0
    assert b["arriere_echu"] == 400.0
    assert len(b["lignes"]) == 2

    r = client.post(f"/api/recouvrement/lot/{lot.id}/19-2", headers=auth(token_a))
    assert r.status_code == 200
    actes = db.query(ActeRecouvrement).filter(ActeRecouvrement.lot_id == lot.id).all()
    assert any(a.type == "activation_19_2" for a in actes)
    d = {e["lot_id"]: e for e in client.get("/api/recouvrement", headers=auth(token_a)).json()}[lot.id]
    assert d["statut"] == "apres_19_2"

    # avant 30 jours → refus
    lot2 = _lot_avec_impaye_echu(db, copro_a, numero="2")
    _md_enregistree(client, token_a, lot2.id, jours_avant=1)
    r = client.post(f"/api/recouvrement/lot/{lot2.id}/19-2", headers=auth(token_a))
    assert r.status_code == 400


def test_frais_et_suppression_acte(client, db, copro_a, syndic_a, token_a):
    lot, p, _, _ = _campagne(db, copro_a)
    r = client.post(f"/api/recouvrement/lot/{lot.id}/acte",
                    json={"type": "frais", "montant": 45.5, "libelle": "Envoi LRE"},
                    headers=auth(token_a))
    assert r.status_code == 200, r.text
    acte_id = r.json()["id"]
    d = client.get(f"/api/recouvrement/lot/{lot.id}", headers=auth(token_a)).json()
    assert d["frais_total"] == 45.5
    assert d["total_reclame"] == 595.5

    assert client.delete(f"/api/recouvrement/acte/{acte_id}", headers=auth(token_a)).status_code == 200
    d = client.get(f"/api/recouvrement/lot/{lot.id}", headers=auth(token_a)).json()
    assert d["frais_total"] == 0.0


def test_interets_taux_legal(client, db, copro_a, syndic_a, token_a):
    lot, p, _, _ = _campagne(db, copro_a)
    r = client.put("/api/copro", json={"taux_legal_retard": 3.65}, headers=auth(token_a))
    assert r.status_code == 200
    _md_enregistree(client, token_a, lot.id, jours_avant=365)
    d = client.get(f"/api/recouvrement/lot/{lot.id}", headers=auth(token_a)).json()
    # 400 € × 3,65 % × 365/365 = 14,60 €
    assert abs(d["interets"] - 14.6) < 0.01
    assert d["statut"] == "delai_19_2_depasse"


def test_recouvrement_reserve_au_syndic(client, db, copro_a, syndic_a, token_a):
    membre = _make_membre(db, "membre.recouv@test.fr", copro_a)
    from app.core.security import create_access_token
    tok_membre = create_access_token(membre.id, copro_a.id)
    assert client.get("/api/recouvrement", headers=auth(tok_membre)).status_code == 403
