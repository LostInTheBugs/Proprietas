"""Historique : soldes bancaires au 31 décembre, pour vérifier qu'aucune opération n'a été oubliée.

Règles retenues (choix de Fred, 09/11/2026) :
- chaque état peut porter deux soldes bancaires facultatifs : compte du syndicat et compte du fonds de
  travaux ;
- entre deux états (mêmes paires que les contrôles des copropriétaires), solde de départ +
  encaissements − dépenses saisis entre les deux dates (date de départ exclue, date d'arrivée
  incluse) est comparé au solde saisi ; le fonds de travaux = mouvements de catégorie
  « fonds_travaux », le reste va au compte du syndicat ;
- un écart AVERTIT sans bloquer la validation (chèque pas encore encaissé…) ;
- un compte sans solde saisi aux deux dates n'est pas contrôlé ;
- la trésorerie affichée part du solde de la base : solde de la base + mouvements datés après elle
  (ceux d'avant sont couverts par la base) ; sans solde de base, elle reste la somme de tous les
  mouvements.
"""
from datetime import date

from app.models.mouvement import Mouvement
from tests.test_reprise_historique import B, B0, Y, URL, _exercice, _ligne, _lots, _valider
from tests.conftest import auth


def _etat(client, token, jour, lignes, syndicat=None, fonds=None):
    corps = {"date": jour.isoformat(), "commentaire": "", "lignes": lignes,
             "solde_banque": syndicat, "solde_banque_fonds": fonds}
    r = client.post(URL, json=corps, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _mouvements(db, copro, l1):
    """Année Y : encaissement 650 (charges), dépense 400 (énergie), encaissement 50 (fonds de travaux).
    Plus une dépense de 80 datée du 31/12/Y-1 (couverte par la base) et une encaissement du 01/01/Y+1."""
    ex = _exercice(db, copro, Y)
    for jour, typ, cat, montant in ((date(Y, 3, 10), "encaissement", "charges", 650),
                                    (date(Y, 4, 2), "depense", "energie", 400),
                                    (date(Y, 5, 5), "encaissement", "fonds_travaux", 50),
                                    (B0, "depense", "entretien", 80),
                                    (date(Y + 1, 1, 1), "encaissement", "charges", 999)):
        db.add(Mouvement(copropriete_id=copro.id, exercice_id=ex.id, date=jour, libelle="x", type=typ,
                         categorie=cat, montant=montant, lot_id=l1.id if typ == "encaissement" else None))
    db.commit()


def test_soldes_bancaires_saisis_et_relus(client, db, copro_a, syndic_a, token_a):
    l1, _ = _lots(db, copro_a)
    e = _etat(client, token_a, B0, [_ligne(l1, Y - 1, 100)], syndicat="1234.56", fonds="-10")
    d = client.get(f"{URL}/{e['id']}", headers=auth(token_a)).json()
    assert (d["solde_banque"], d["solde_banque_fonds"]) == (1234.56, -10)
    # Facultatifs : absents = non saisis.
    e2 = _etat(client, token_a, B, [_ligne(l1, Y, 0)])
    assert (e2["solde_banque"], e2["solde_banque_fonds"]) == (None, None)


def test_controle_banque_concordant(client, db, copro_a, syndic_a, token_a):
    l1, _ = _lots(db, copro_a)
    base = _etat(client, token_a, B0, [_ligne(l1, Y - 1, 100)], syndicat=1000, fonds=200)
    assert _valider(client, token_a, base["id"]).status_code == 200
    _mouvements(db, copro_a, l1)
    # Syndicat : 1000 + 650 − 400 = 1250 ; fonds : 200 + 50 = 250.
    e = _etat(client, token_a, B, [_ligne(l1, Y, 0)], syndicat=1250, fonds=250)
    d = client.get(f"{URL}/{e['id']}", headers=auth(token_a)).json()
    banque = {c["compte"]: c for c in d["controles_banque"]}
    assert banque["syndicat"] == {**banque["syndicat"], "depart": B0.isoformat(), "date": B.isoformat(),
                                  "solde_depart": 1000, "encaissements": 650, "depenses": 400,
                                  "calcule": 1250, "saisi": 1250, "ecart": 0, "ok": True}
    assert (banque["fonds_travaux"]["calcule"], banque["fonds_travaux"]["ok"]) == (250, True)
    assert d["banque_ok"] is True


def test_ecart_bancaire_averti_sans_bloquer(client, db, copro_a, syndic_a, token_a):
    l1, _ = _lots(db, copro_a)
    base = _etat(client, token_a, B0, [_ligne(l1, Y - 1, 100)], syndicat=1000)
    _valider(client, token_a, base["id"])
    _mouvements(db, copro_a, l1)
    # La banque dit 1150 : une dépense de 100 € n'a pas été saisie. Lot 1 : 100 − 650 − 50 = −600 (crédit).
    e = _etat(client, token_a, B, [_ligne(l1, Y, -600)], syndicat=1150)
    d = client.get(f"{URL}/{e['id']}", headers=auth(token_a)).json()
    [c] = d["controles_banque"]                          # fonds de travaux non saisi : pas de contrôle
    assert (c["compte"], c["calcule"], c["saisi"], c["ecart"], c["ok"]) == ("syndicat", 1250, 1150, -100, False)
    assert d["banque_ok"] is False
    # Les soldes des copropriétaires tombent juste : la validation passe malgré l'écart bancaire.
    assert _valider(client, token_a, e["id"]).status_code == 200
    liste = {x["date"]: x for x in client.get(URL, headers=auth(token_a)).json()}
    assert liste[B.isoformat()]["banque_ok"] is False


def test_tresorerie_part_du_solde_de_la_base(client, db, copro_a, syndic_a, token_a):
    l1, _ = _lots(db, copro_a)
    _mouvements(db, copro_a, l1)
    # Sans base : somme de tous les mouvements (−80 + 650 − 400 + 999 ; fonds 50).
    t = client.get("/api/copro/tresorerie", headers=auth(token_a)).json()
    assert (t["solde_compte"], t["fonds_travaux_solde"]) == (1169, 50)
    base = _etat(client, token_a, B0, [_ligne(l1, Y - 1, 100)], syndicat=1000, fonds=200)
    _valider(client, token_a, base["id"])
    # Base au 31/12/Y-1 : 1000 + mouvements après (650 − 400 + 999) ; la dépense du 31/12/Y-1 est couverte.
    t = client.get("/api/copro/tresorerie", headers=auth(token_a)).json()
    assert (t["solde_compte"], t["fonds_travaux_solde"]) == (2249, 250)
    recap = client.get("/api/recap", headers=auth(token_a)).json()
    assert (recap["tresorerie_syndicat"], recap["tresorerie_fonds_travaux"]) == (2249, 250)


def test_brouillon_sans_effet_sur_la_tresorerie(client, db, copro_a, syndic_a, token_a):
    l1, _ = _lots(db, copro_a)
    _mouvements(db, copro_a, l1)
    _etat(client, token_a, B0, [_ligne(l1, Y - 1, 100)], syndicat=1000, fonds=200)   # non validé
    t = client.get("/api/copro/tresorerie", headers=auth(token_a)).json()
    assert t["solde_compte"] == 1169


# ---------------------------------------------------------------- tâche 46 : état déjà validé
# Cas réel : la base de Fred était validée avant l'arrivée des soldes bancaires ; il ne pouvait plus
# rien saisir (« je ne peux pas éditer la ligne dans historique »).

def _banque(client, token, etat_id, syndicat, fonds=None):
    return client.put(f"{URL}/{etat_id}/banque", json={"solde_banque": syndicat, "solde_banque_fonds": fonds},
                      headers=auth(token))


def test_soldes_bancaires_d_un_etat_valide(client, db, copro_a, syndic_a, token_a):
    from app.models.audit import AuditLog
    l1, _ = _lots(db, copro_a)
    base = _etat(client, token_a, B0, [_ligne(l1, Y - 1, 100)])
    _valider(client, token_a, base["id"])
    _mouvements(db, copro_a, l1)
    r = _banque(client, token_a, base["id"], "1000", "200")
    assert r.status_code == 200, r.text
    assert (r.json()["solde_banque"], r.json()["solde_banque_fonds"], r.json()["valide"]) == (1000, 200, True)
    # Le reste de l'état ne bouge pas, et la trésorerie part désormais de ces soldes.
    assert r.json()["total_charges"] == 100
    t = client.get("/api/copro/tresorerie", headers=auth(token_a)).json()
    assert (t["solde_compte"], t["fonds_travaux_solde"]) == (2249, 250)
    detail = db.query(AuditLog).filter(AuditLog.action == "reprise_banque_modifiee").one().detail
    assert "31/12" in detail and "1000" in detail.replace(" ", "").replace(",00", "")
    # Effacer (null) est permis : retour au calcul sans solde de départ.
    assert _banque(client, token_a, base["id"], None).json()["solde_banque"] is None


def test_soldes_bancaires_d_un_brouillon_aussi(client, db, copro_a, syndic_a, token_a):
    l1, _ = _lots(db, copro_a)
    e = _etat(client, token_a, B0, [_ligne(l1, Y - 1, 100)])
    assert _banque(client, token_a, e["id"], "50.5").json()["solde_banque"] == 50.5


def test_soldes_bancaires_reserves_et_isoles(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b):
    from app.core.security import create_access_token
    from tests.conftest import _make_membre
    l1, _ = _lots(db, copro_a)
    e = _etat(client, token_a, B0, [_ligne(l1, Y - 1, 100)])
    assert _banque(client, token_b, e["id"], "1").status_code == 404
    tok = create_access_token(_make_membre(db, "m@test.fr", copro_a).id, copro_a.id)
    assert _banque(client, tok, e["id"], "1").status_code == 403
