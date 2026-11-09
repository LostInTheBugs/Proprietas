"""Modifier plusieurs mouvements d'un coup (sélection dans Comptes).

Règles retenues :
- le syndic choisit des mouvements de sa copropriété et un ou plusieurs champs à changer : exercice,
  type, catégorie, contrat (contrat_id null = délier) ; les autres champs ne bougent pas ;
- tout ou rien : un mouvement d'une autre copropriété, un exercice ou un contrat d'une autre
  copropriété, un type ou une catégorie inconnus → 422 et rien n'est modifié ;
- une dépense ne quitte pas (et n'entre pas dans) un exercice dont les charges sont régularisées ;
- au moins un mouvement et au moins un champ ; une ligne au journal d'audit.
"""
from datetime import date

from app.models.appel import AppelFonds
from app.models.audit import AuditLog
from app.models.contrat import Contrat
from app.models.mouvement import Mouvement
from tests.conftest import auth

Y = date.today().year
URL = "/api/mouvements/groupe"


def _base(client, db, copro, token):
    ex = {}
    for annee in (Y - 1, Y):
        ex[annee] = client.post("/api/exercices", json={"annee": annee}, headers=auth(token)).json()["id"]
    edf = Contrat(copropriete_id=copro.id, libelle="EDF", type="energie")
    db.add(edf)
    db.commit()
    ids = []
    for jour, typ, cat in ((f"{Y - 1}-12-10", "depense", "autre"), (f"{Y - 1}-12-20", "depense", "autre"),
                           (f"{Y}-01-05", "encaissement", "charges")):
        r = client.post(f"/api/exercices/{ex[Y]}/mouvements", json={
            "date": jour, "libelle": "Ligne", "type": typ, "categorie": cat, "montant": 100}, headers=auth(token))
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])
    return ex, edf, ids


def _etat(db, ids):
    db.expire_all()
    return [(m.exercice_id, m.type, m.categorie, m.contrat_id, float(m.montant), m.libelle)
            for m in db.query(Mouvement).filter(Mouvement.id.in_(ids)).order_by(Mouvement.id)]


def test_modifier_exercice_categorie_et_contrat(client, db, copro_a, syndic_a, token_a):
    ex, edf, ids = _base(client, db, copro_a, token_a)
    r = client.post(URL, json={"ids": ids[:2], "exercice_id": ex[Y - 1], "categorie": "energie",
                               "contrat_id": edf.id}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert r.json()["modifies"] == 2
    etat = _etat(db, ids)
    assert etat[0][:4] == (ex[Y - 1], "depense", "energie", edf.id) == etat[1][:4]
    assert etat[0][4:] == (100.0, "Ligne")                                  # le reste ne bouge pas
    assert etat[2][:4] == (ex[Y], "encaissement", "charges", None)          # non sélectionné
    detail = db.query(AuditLog).filter(AuditLog.action == "mouvements_modifies").one().detail
    assert "2 mouvement(s)" in detail and "catégorie energie" in detail


def test_changer_le_type_et_delier_le_contrat(client, db, copro_a, syndic_a, token_a):
    ex, edf, ids = _base(client, db, copro_a, token_a)
    client.post(URL, json={"ids": ids[:1], "contrat_id": edf.id}, headers=auth(token_a))
    r = client.post(URL, json={"ids": ids[:1], "type": "encaissement", "contrat_id": None}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert _etat(db, ids)[0][1:4] == ("encaissement", "autre", None)
    # Sans contrat_id dans la requête, le contrat ne change pas.
    client.post(URL, json={"ids": ids[1:2], "contrat_id": edf.id}, headers=auth(token_a))
    client.post(URL, json={"ids": ids[1:2], "categorie": "entretien"}, headers=auth(token_a))
    assert _etat(db, ids)[1][2:4] == ("entretien", edf.id)


def test_tout_ou_rien(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b):
    ex, edf, ids = _base(client, db, copro_a, token_a)
    ex_b = client.post("/api/exercices", json={"annee": Y}, headers=auth(token_b)).json()["id"]
    m_b = client.post(f"/api/exercices/{ex_b}/mouvements", json={
        "date": f"{Y}-02-01", "libelle": "B", "type": "depense", "categorie": "autre", "montant": 5},
        headers=auth(token_b)).json()["id"]
    c_b = Contrat(copropriete_id=copro_b.id, libelle="Autre")
    db.add(c_b)
    db.commit()
    avant = _etat(db, ids)
    for corps in ({"ids": ids + [m_b], "categorie": "energie"},       # mouvement d'une autre copropriété
                  {"ids": ids, "exercice_id": ex_b},                  # exercice d'une autre copropriété
                  {"ids": ids, "contrat_id": c_b.id},                 # contrat d'une autre copropriété
                  {"ids": ids, "type": "virement"},
                  {"ids": ids, "categorie": "inconnue"},
                  {"ids": [], "categorie": "energie"},                # aucun mouvement
                  {"ids": ids}):                                      # aucun champ
        assert client.post(URL, json=corps, headers=auth(token_a)).status_code == 422, corps
    assert _etat(db, ids) == avant


def test_exercice_regularise_bloque(client, db, copro_a, syndic_a, token_a):
    ex, _, ids = _base(client, db, copro_a, token_a)
    db.add(AppelFonds(exercice_id=ex[Y - 1], regularisation_de_id=ex[Y - 1], libelle=f"Régularisation {Y - 1}",
                      date_emission=date(Y, 3, 1), date_echeance=date(Y, 3, 31), montant_total=0))
    db.commit()
    avant = _etat(db, ids)
    r = client.post(URL, json={"ids": ids, "exercice_id": ex[Y - 1]}, headers=auth(token_a))
    assert r.status_code == 422 and "régularisées" in r.json()["detail"]
    assert _etat(db, ids) == avant
    # Un encaissement seul peut y aller.
    assert client.post(URL, json={"ids": ids[2:], "exercice_id": ex[Y - 1]}, headers=auth(token_a)).status_code == 200


def test_reserve_au_syndic(client, db, copro_a, syndic_a, token_a):
    from app.core.security import create_access_token
    from tests.conftest import _make_membre
    _, _, ids = _base(client, db, copro_a, token_a)
    tok = create_access_token(_make_membre(db, "m@test.fr", copro_a).id, copro_a.id)
    assert client.post(URL, json={"ids": ids, "categorie": "energie"}, headers=auth(tok)).status_code == 403
