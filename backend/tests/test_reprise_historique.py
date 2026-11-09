"""Reprise de l'historique : états de fin d'exercice (31/12) saisis par le syndic.

L'application n'est jamais mise en place à partir de zéro : il existe un historique. Le syndic
saisit, par lot, ce que chaque copropriétaire devait au 31 décembre d'une année (ventilé par
exercice d'origine, pour l'art. 19-2), puis complète éventuellement en remontant d'année en année.

Règles retenues :
- un état est daté du 31 décembre (exercice = année civile), jamais dans le futur ;
- un état en brouillon n'a aucun effet ;
- l'état validé le plus ancien est la BASE : il génère un appel « Reprise de solde » par exercice
  d'origine (montant négatif = crédit), et tout appel émis ou encaissement daté jusqu'à sa date
  est COUVERT par lui (ignoré dans les soldes, pour ne jamais compter deux fois) ;
- un état validé plus récent est un POINT DE CONTRÔLE : base + appels − encaissements de la
  période doit lui être égal, lot par lot, sinon la validation est refusée ;
- valider un état plus ancien que la base (remonter d'une année) exige que tous les points de
  contrôle tombent juste à partir de lui ; il devient alors la base (appels de reprise régénérés) ;
- un état validé ne se modifie ni ne se supprime ; un appel de reprise ne se supprime pas à la main ;
- les appels de reprise ne sont pas des provisions de l'exercice (régularisation des charges).
"""
from datetime import date, timedelta

from app.models.appel import AppelFonds, AppelLot
from app.models.exercice import Exercice
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.core.security import create_access_token
from tests.conftest import _make_membre, auth

AUJOURDHUI = date.today()
Y = AUJOURDHUI.year - 1            # dernier exercice clos
B = date(Y, 12, 31)                # état au 31/12 du dernier exercice clos
B0 = date(Y - 1, 12, 31)           # état de l'année précédente
URL = "/api/reprise/etats"


def _lots(db, copro):
    p1 = _make_membre(db, "un@test.fr", copro)
    p2 = _make_membre(db, "deux@test.fr", copro)
    l1 = Lot(copropriete_id=copro.id, numero="1", tantiemes=600, proprietaire_id=p1.id)
    l2 = Lot(copropriete_id=copro.id, numero="2", tantiemes=400, proprietaire_id=p2.id)
    db.add_all([l1, l2])
    db.commit()
    return l1, l2


def _ligne(lot, exercice, charges=0, fonds=0):
    return {"lot_id": lot.id, "exercice_origine": exercice, "montant_charges": charges,
            "montant_fonds_travaux": fonds}


def _creer(client, token, jour, lignes, commentaire=""):
    return client.post(URL, json={"date": jour.isoformat(), "commentaire": commentaire, "lignes": lignes},
                       headers=auth(token))


def _valider(client, token, etat_id):
    return client.post(f"{URL}/{etat_id}/valider", headers=auth(token))


def _base(client, token, jour, lignes):
    r = _creer(client, token, jour, lignes)
    assert r.status_code == 200, r.text
    v = _valider(client, token, r.json()["id"])
    assert v.status_code == 200, v.text
    return r.json()["id"]


def _exercice(db, copro, annee):
    ex = db.query(Exercice).filter(Exercice.copropriete_id == copro.id, Exercice.annee == annee).first()
    if ex is None:
        ex = Exercice(copropriete_id=copro.id, annee=annee, cloture=annee < AUJOURDHUI.year)
        db.add(ex)
        db.flush()
    return ex


def _annee_detaillee(db, copro, l1, l2, annee):
    """Appel de provisions 600 / 400 émis le 1er mars, payés 650 / 400 le 10 mars.
    Variation de l'année : lot 1 −50, lot 2 0."""
    ex = _exercice(db, copro, annee)
    a = AppelFonds(exercice_id=ex.id, libelle=f"Provisions {annee}", date_emission=date(annee, 3, 1),
                   date_echeance=date(annee, 3, 15), montant_total=1000)
    db.add(a)
    db.flush()
    db.add_all([AppelLot(appel_id=a.id, lot_id=l1.id, montant_charges=600, montant_fonds_travaux=0),
                AppelLot(appel_id=a.id, lot_id=l2.id, montant_charges=400, montant_fonds_travaux=0)])
    for lot, montant in ((l1, 650), (l2, 400)):
        db.add(Mouvement(copropriete_id=copro.id, exercice_id=ex.id, date=date(annee, 3, 10),
                         libelle="Paiement", type="encaissement", categorie="charges", montant=montant,
                         lot_id=lot.id))
    db.commit()


def _soldes(client, token):
    return {s["lot"]["numero"]: s["solde"] for s in client.get("/api/lots/soldes", headers=auth(token)).json()}


def _reprises(db):
    return db.query(AppelFonds).filter(AppelFonds.libelle.like("Reprise de solde%")).all()


def test_etat_au_31_decembre_seulement(client, db, copro_a, syndic_a, token_a):
    l1, _ = _lots(db, copro_a)
    assert _creer(client, token_a, date(Y, 12, 30), [_ligne(l1, Y, 100)]).status_code == 422
    assert _creer(client, token_a, date(AUJOURDHUI.year + 1, 12, 31), [_ligne(l1, Y, 100)]).status_code == 422
    assert _creer(client, token_a, B, [_ligne(l1, Y, 100)]).status_code == 200
    assert _creer(client, token_a, B, [_ligne(l1, Y, 100)]).status_code == 409


def test_lignes_invalides(client, db, copro_a, syndic_a, token_a):
    l1, _ = _lots(db, copro_a)
    # Exercice d'origine postérieur à la date de l'état.
    assert _creer(client, token_a, B, [_ligne(l1, Y + 1, 100)]).status_code == 422
    # Deux lignes pour le même lot et le même exercice.
    assert _creer(client, token_a, B, [_ligne(l1, Y, 100), _ligne(l1, Y, 50)]).status_code == 422


def test_brouillon_sans_effet(client, db, copro_a, syndic_a, token_a):
    l1, _ = _lots(db, copro_a)
    r = _creer(client, token_a, B, [_ligne(l1, Y, 150)])
    assert r.status_code == 200, r.text
    assert r.json()["valide"] is False
    assert _soldes(client, token_a)["1"] == 0
    assert _reprises(db) == []


def test_validation_genere_les_appels_de_reprise(client, db, copro_a, syndic_a, token_a):
    l1, l2 = _lots(db, copro_a)
    _base(client, token_a, B, [_ligne(l1, Y, 100), _ligne(l1, Y - 1, 50, 20), _ligne(l2, Y, -30)])
    appels = sorted(_reprises(db), key=lambda a: a.exercice.annee)
    assert [a.exercice.annee for a in appels] == [Y - 1, Y]
    assert all(f"au {B:%d/%m/%Y}" in a.libelle for a in appels)
    assert all(a.date_emission == B for a in appels)
    # Exercices d'origine créés clôturés, sans approbation (à saisir par le syndic).
    assert all(a.exercice.cloture and a.exercice.comptes_approuves_le is None for a in appels)
    parts = {(p.appel.exercice.annee, p.lot_id): p for a in appels for p in a.parts}
    assert float(parts[(Y - 1, l1.id)].montant_charges) == 50
    assert float(parts[(Y - 1, l1.id)].montant_fonds_travaux) == 20
    assert float(parts[(Y, l2.id)].montant_charges) == -30
    assert _soldes(client, token_a) == {"1": 170, "2": -30}
    assert client.get(f"/api/recouvrement/lot/{l1.id}", headers=auth(token_a)).json()["solde"] == 170
    etats = client.get(URL, headers=auth(token_a)).json()
    assert [(e["date"], e["role"]) for e in etats] == [(B.isoformat(), "base")]


def test_19_2_distingue_les_exercices_approuves(client, db, copro_a, syndic_a, token_a):
    from app.models.copropriete import Copropriete
    from app.services.recouvrement import breakdown_19_2

    l1, _ = _lots(db, copro_a)
    _base(client, token_a, B, [_ligne(l1, Y, 100), _ligne(l1, Y - 1, 50, 20)])
    db.expire_all()
    _exercice(db, copro_a, Y - 1).comptes_approuves_le = date(Y, 6, 1)
    _exercice(db, copro_a, AUJOURDHUI.year)
    db.commit()
    b = breakdown_19_2(db, db.get(Copropriete, copro_a.id), db.get(Lot, l1.id))
    assert b["precedents_approuves"] == 70
    assert b["precedents_non_approuves"] == 100
    assert b["exercices_non_approuves"] == [Y]


def test_operations_couvertes_par_la_base(client, db, copro_a, syndic_a, token_a):
    l1, l2 = _lots(db, copro_a)
    _base(client, token_a, B, [_ligne(l1, Y, 50)])
    # Le détail de l'année Y est déjà compris dans l'état au 31/12/Y : aucun effet sur les soldes.
    _annee_detaillee(db, copro_a, l1, l2, Y)
    assert _soldes(client, token_a) == {"1": 50, "2": 0}
    assert client.get(f"/api/recouvrement/lot/{l1.id}", headers=auth(token_a)).json()["solde"] == 50
    # Après la base, tout compte normalement.
    ex = _exercice(db, copro_a, AUJOURDHUI.year)
    a = AppelFonds(exercice_id=ex.id, libelle="Provisions T1", date_emission=date(AUJOURDHUI.year, 1, 2),
                   date_echeance=date(AUJOURDHUI.year, 1, 15), montant_total=100)
    db.add(a)
    db.flush()
    db.add(AppelLot(appel_id=a.id, lot_id=l1.id, montant_charges=100, montant_fonds_travaux=0))
    db.add(Mouvement(copropriete_id=copro_a.id, exercice_id=ex.id, date=date(AUJOURDHUI.year, 1, 3),
                     libelle="Paiement", type="encaissement", categorie="charges", montant=30, lot_id=l1.id))
    db.commit()
    assert _soldes(client, token_a)["1"] == 120
    assert client.get(f"/api/recouvrement/lot/{l1.id}", headers=auth(token_a)).json()["solde"] == 120


def test_point_de_controle(client, db, copro_a, syndic_a, token_a):
    l1, l2 = _lots(db, copro_a)
    _base(client, token_a, B0, [_ligne(l1, Y - 1, 100)])
    _annee_detaillee(db, copro_a, l1, l2, Y)
    # Attendu au 31/12/Y : lot 1 = 100 + 600 − 650 = 50 ; lot 2 = 0.
    r = _creer(client, token_a, B, [_ligne(l1, Y, 60)])
    etat_id = r.json()["id"]
    v = _valider(client, token_a, etat_id)
    assert v.status_code == 422
    assert "écart" in v.json()["detail"]
    d = client.get(f"{URL}/{etat_id}", headers=auth(token_a)).json()
    [c] = d["controles"]
    assert c["ok"] is False
    lot1 = next(l for l in c["lignes"] if l["lot_numero"] == "1")
    assert (lot1["attendu"], lot1["calcule"], lot1["ecart"]) == (60, 50, 10)
    corps = {"date": B.isoformat(), "commentaire": "", "lignes": [_ligne(l1, Y, 50)]}
    assert client.put(f"{URL}/{etat_id}", json=corps, headers=auth(token_a)).status_code == 200
    assert _valider(client, token_a, etat_id).status_code == 200
    etats = {e["date"]: e for e in client.get(URL, headers=auth(token_a)).json()}
    assert etats[B.isoformat()]["role"] == "point_de_controle"
    assert etats[B.isoformat()]["controle_ok"] is True
    # Un point de contrôle ne génère aucun appel.
    assert len(_reprises(db)) == 1
    assert _soldes(client, token_a) == {"1": 50, "2": 0}


def test_remonter_d_une_annee(client, db, copro_a, syndic_a, token_a):
    l1, l2 = _lots(db, copro_a)
    _base(client, token_a, B, [_ligne(l1, Y, 50)])
    _annee_detaillee(db, copro_a, l1, l2, Y)
    assert _soldes(client, token_a) == {"1": 50, "2": 0}
    _base(client, token_a, B0, [_ligne(l1, Y - 1, 100)])
    db.expire_all()
    libelles = [a.libelle for a in _reprises(db)]
    assert len(libelles) == 1 and f"au {B0:%d/%m/%Y}" in libelles[0]
    etats = {e["date"]: e["role"] for e in client.get(URL, headers=auth(token_a)).json()}
    assert etats == {B0.isoformat(): "base", B.isoformat(): "point_de_controle"}
    # Le détail de l'année Y compte désormais, et les soldes n'ont pas bougé.
    assert _soldes(client, token_a) == {"1": 50, "2": 0}


def test_remonter_refuse_si_le_controle_echoue(client, db, copro_a, syndic_a, token_a):
    l1, l2 = _lots(db, copro_a)
    _base(client, token_a, B, [_ligne(l1, Y, 50)])
    _annee_detaillee(db, copro_a, l1, l2, Y)
    r = _creer(client, token_a, B0, [_ligne(l1, Y - 1, 120)])
    v = _valider(client, token_a, r.json()["id"])
    assert v.status_code == 422
    assert "écart" in v.json()["detail"]
    db.expire_all()
    libelles = [a.libelle for a in _reprises(db)]
    assert len(libelles) == 1 and f"au {B:%d/%m/%Y}" in libelles[0]
    assert _soldes(client, token_a) == {"1": 50, "2": 0}


def test_etat_valide_ni_modifiable_ni_supprimable(client, db, copro_a, syndic_a, token_a):
    l1, _ = _lots(db, copro_a)
    etat_id = _base(client, token_a, B, [_ligne(l1, Y, 50)])
    corps = {"date": B.isoformat(), "commentaire": "", "lignes": [_ligne(l1, Y, 60)]}
    assert client.put(f"{URL}/{etat_id}", json=corps, headers=auth(token_a)).status_code == 422
    assert client.delete(f"{URL}/{etat_id}", headers=auth(token_a)).status_code == 422
    assert _valider(client, token_a, etat_id).status_code == 409


def test_brouillon_supprimable(client, db, copro_a, syndic_a, token_a):
    l1, _ = _lots(db, copro_a)
    etat_id = _creer(client, token_a, B, [_ligne(l1, Y, 50)]).json()["id"]
    assert client.delete(f"{URL}/{etat_id}", headers=auth(token_a)).status_code == 200
    assert client.get(URL, headers=auth(token_a)).json() == []


def test_appel_de_reprise_non_supprimable(client, db, copro_a, syndic_a, token_a):
    l1, _ = _lots(db, copro_a)
    _base(client, token_a, B, [_ligne(l1, Y, 50)])
    [appel] = _reprises(db)
    assert client.delete(f"/api/appels/{appel.id}", headers=auth(token_a)).status_code == 422
    assert client.delete(f"/api/exercices/{appel.exercice_id}", headers=auth(token_a)).status_code == 422
    assert _soldes(client, token_a)["1"] == 50


def test_regularisation_ignore_les_appels_de_reprise(client, db, copro_a, syndic_a, token_a):
    l1, _ = _lots(db, copro_a)
    _base(client, token_a, B, [_ligne(l1, Y, 100)])
    db.expire_all()
    ex = _exercice(db, copro_a, Y)
    ex.comptes_approuves_le = AUJOURDHUI - timedelta(days=1)
    db.commit()
    d = client.get(f"/api/exercices/{ex.id}/regularisation", headers=auth(token_a)).json()
    assert {l["lot_numero"]: l["provisions"] for l in d["lignes"]}["1"] == 0


def test_reserve_au_syndic(client, db, copro_a, syndic_a, token_a):
    l1, _ = _lots(db, copro_a)
    tok = create_access_token(l1.proprietaire_id, copro_a.id)
    assert client.get(URL, headers=auth(tok)).status_code == 403
    assert _creer(client, tok, B, [_ligne(l1, Y, 50)]).status_code == 403


def test_isolation_entre_coproprietes(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b):
    l1, _ = _lots(db, copro_a)
    etat_id = _creer(client, token_a, B, [_ligne(l1, Y, 50)]).json()["id"]
    assert client.get(f"{URL}/{etat_id}", headers=auth(token_b)).status_code == 404
    assert _valider(client, token_b, etat_id).status_code == 404
    # Un lot d'une autre copropriété est refusé.
    assert _creer(client, token_b, B, [_ligne(l1, Y, 50)]).status_code == 422
