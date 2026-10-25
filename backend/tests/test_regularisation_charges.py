"""Régularisation des charges après approbation des comptes.

- Loi n° 65-557, art. 14-1 : les copropriétaires versent des PROVISIONS sur le budget
  prévisionnel ; l'approbation des comptes révèle les charges RÉELLES de l'exercice.
- Décret n° 67-223, art. 6-2, 3° : « le trop ou moins perçu sur provisions, révélé par
  l'approbation des comptes, est porté au crédit ou au débit du compte de celui qui est
  copropriétaire lors de l'approbation des comptes » (Cass. 3e civ., 14 avr. 2016).

Règles retenues :
- seulement pour un exercice dont les comptes sont approuvés, une seule fois ;
- charges réelles = dépenses de l'exercice hors fonds de travaux et hors travaux (financés
  par des appels distincts) ; une dépense rattachée à un lot est imputée à ce seul lot, les
  autres sont réparties aux tantièmes (plus fort reste) ;
- provisions = parts « charges » des appels de l'exercice ; les cotisations au fonds de
  travaux ne sont jamais régularisées (elles restent acquises au syndicat, art. 14-2-1) ;
- écart = réel − provisions : complément appelé (> 0) ou crédit (< 0), dans un appel
  « Régularisation des charges » rattaché à l'exercice approuvé ; le crédit vient en
  déduction des sommes dues par le lot.
"""
from datetime import date, timedelta

from app.models.appel import AppelFonds, AppelLot
from app.models.exercice import Exercice
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.core.security import create_access_token
from tests.conftest import _make_membre, auth

AUJOURDHUI = date.today()


def _exercice(db, copro):
    """2 lots (600 / 400 millièmes). Exercice N-1 : provisions 600 / 400 (+ fonds de travaux
    30 / 20). Dépenses : charges 700 + assurance 200 (communes), 50 imputés au lot 2,
    travaux 5 000 et fonds de travaux 100 (exclus).
    Attendu : lot 1 réel 540, provisions 600 → crédit 60 ; lot 2 réel 360 + 50 = 410,
    provisions 400 → complément 10."""
    p1 = _make_membre(db, "un@test.fr", copro)
    p2 = _make_membre(db, "deux@test.fr", copro)
    l1 = Lot(copropriete_id=copro.id, numero="1", tantiemes=600, proprietaire_id=p1.id)
    l2 = Lot(copropriete_id=copro.id, numero="2", tantiemes=400, proprietaire_id=p2.id)
    db.add_all([l1, l2])
    ex = Exercice(copropriete_id=copro.id, annee=AUJOURDHUI.year - 1, cloture=True,
                  comptes_approuves_le=AUJOURDHUI - timedelta(days=5))
    db.add(ex)
    db.flush()
    a = AppelFonds(exercice_id=ex.id, libelle="Provisions", date_emission=date(ex.annee, 1, 1),
                   date_echeance=date(ex.annee, 1, 15), montant_total=1000, inclut_fonds_travaux=True,
                   fonds_travaux_montant=50)
    db.add(a)
    db.flush()
    db.add_all([AppelLot(appel_id=a.id, lot_id=l1.id, montant_charges=600, montant_fonds_travaux=30),
                AppelLot(appel_id=a.id, lot_id=l2.id, montant_charges=400, montant_fonds_travaux=20)])
    for libelle, cat, montant, lot in (("Entretien", "charges", 700, None), ("Assurance", "assurance", 200, None),
                                       ("Débouchage lot 2", "entretien", 50, l2), ("Toiture", "travaux", 5000, None),
                                       ("Placement fonds", "fonds_travaux", 100, None)):
        db.add(Mouvement(copropriete_id=copro.id, exercice_id=ex.id, date=date(ex.annee, 6, 1), libelle=libelle,
                         type="depense", categorie=cat, montant=montant, lot_id=lot.id if lot else None))
    db.commit()
    return ex, l1, l2


def _url(ex):
    return f"/api/exercices/{ex.id}/regularisation"


def test_apercu_par_lot(client, db, copro_a, syndic_a, token_a):
    ex, l1, l2 = _exercice(db, copro_a)
    r = client.get(_url(ex), headers=auth(token_a))
    assert r.status_code == 200, r.text
    d = r.json()
    lignes = {l["lot_numero"]: l for l in d["lignes"]}
    assert (lignes["1"]["provisions"], lignes["1"]["charges_reelles"], lignes["1"]["ecart"]) == (600, 540, -60)
    assert (lignes["2"]["provisions"], lignes["2"]["charges_reelles"], lignes["2"]["ecart"]) == (400, 410, 10)
    assert d["total_provisions"] == 1000 and d["total_charges_reelles"] == 950 and d["total_ecart"] == -50
    assert d["appel_id"] is None and d["approuve"] is True


def test_refusee_si_comptes_non_approuves(client, db, copro_a, syndic_a, token_a):
    ex, *_ = _exercice(db, copro_a)
    ex.comptes_approuves_le = None
    db.commit()
    r = client.post(_url(ex), json={"date_echeance": (AUJOURDHUI + timedelta(days=30)).isoformat()},
                    headers=auth(token_a))
    assert r.status_code == 422
    assert "approbation" in r.json()["detail"]


def test_appel_de_regularisation(client, db, copro_a, syndic_a, token_a):
    ex, l1, l2 = _exercice(db, copro_a)
    echeance = (AUJOURDHUI + timedelta(days=30)).isoformat()
    r = client.post(_url(ex), json={"date_echeance": echeance}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    appel = db.get(AppelFonds, r.json()["appel_id"])
    assert appel.exercice_id == ex.id and appel.regularisation_de_id == ex.id
    assert "Régularisation des charges" in appel.libelle
    assert appel.date_echeance.isoformat() == echeance
    parts = {p.lot_id: p for p in appel.parts}
    assert float(parts[l1.id].montant_charges) == -60 and float(parts[l2.id].montant_charges) == 10
    # Le fonds de travaux n'est jamais régularisé.
    assert float(parts[l1.id].montant_fonds_travaux) == 0 and float(parts[l2.id].montant_fonds_travaux) == 0


def test_une_seule_regularisation_par_exercice(client, db, copro_a, syndic_a, token_a):
    ex, *_ = _exercice(db, copro_a)
    corps = {"date_echeance": (AUJOURDHUI + timedelta(days=30)).isoformat()}
    assert client.post(_url(ex), json=corps, headers=auth(token_a)).status_code == 200
    assert client.post(_url(ex), json=corps, headers=auth(token_a)).status_code == 409
    d = client.get(_url(ex), headers=auth(token_a)).json()
    assert d["appel_id"] is not None
    # L'appel de régularisation n'est pas compté comme une provision : les écarts restent les mêmes.
    assert {l["lot_numero"]: l["ecart"] for l in d["lignes"]} == {"1": -60, "2": 10}


def test_le_credit_vient_en_deduction_des_sommes_dues(client, db, copro_a, syndic_a, token_a):
    ex, l1, _ = _exercice(db, copro_a)
    courant = Exercice(copropriete_id=copro_a.id, annee=AUJOURDHUI.year, cloture=False)
    db.add(courant)
    db.flush()
    a = AppelFonds(exercice_id=courant.id, libelle="Provisions T1", date_emission=AUJOURDHUI - timedelta(days=20),
                   date_echeance=AUJOURDHUI - timedelta(days=10), montant_total=100)
    db.add(a)
    db.flush()
    db.add(AppelLot(appel_id=a.id, lot_id=l1.id, montant_charges=100, montant_fonds_travaux=0))
    # Les provisions de l'exercice approuvé (630) ont été payées.
    db.add(Mouvement(copropriete_id=copro_a.id, exercice_id=ex.id, date=date(ex.annee, 1, 10),
                     libelle="Paiement", type="encaissement", categorie="charges", montant=630, lot_id=l1.id))
    db.commit()
    assert client.get(f"/api/recouvrement/lot/{l1.id}", headers=auth(token_a)).json()["solde"] == 100
    client.post(_url(ex), json={"date_echeance": AUJOURDHUI.isoformat()}, headers=auth(token_a))
    # Trop-perçu de 60 € : il réduit la dette du T1, même si l'appel T1 est antérieur.
    assert client.get(f"/api/recouvrement/lot/{l1.id}", headers=auth(token_a)).json()["solde"] == 40


def test_reserve_au_syndic(client, db, copro_a, syndic_a, token_a):
    ex, l1, _ = _exercice(db, copro_a)
    tok = create_access_token(l1.proprietaire_id, copro_a.id)
    assert client.get(_url(ex), headers=auth(tok)).status_code == 403


def test_exercice_d_une_autre_copropriete(client, db, copro_a, copro_b, syndic_a, syndic_b, token_b):
    ex, *_ = _exercice(db, copro_a)
    assert client.get(_url(ex), headers=auth(token_b)).status_code == 404


def test_echeance_passee_refusee(client, db, copro_a, syndic_a, token_a):
    ex, *_ = _exercice(db, copro_a)
    r = client.post(_url(ex), json={"date_echeance": (AUJOURDHUI - timedelta(days=1)).isoformat()},
                    headers=auth(token_a))
    assert r.status_code == 422


def test_rien_a_regulariser(client, db, copro_a, syndic_a, token_a):
    ex, *_ = _exercice(db, copro_a)
    # Dépenses réelles égales aux provisions : 1 000 € communs, plus de dépense propre au lot 2.
    for m in db.query(Mouvement).filter(Mouvement.exercice_id == ex.id).all():
        if m.libelle == "Entretien":
            m.montant = 800
        if m.libelle == "Débouchage lot 2":
            db.delete(m)
    db.commit()
    r = client.post(_url(ex), json={"date_echeance": AUJOURDHUI.isoformat()}, headers=auth(token_a))
    assert r.status_code == 422
    assert "rien à régulariser" in r.json()["detail"]
