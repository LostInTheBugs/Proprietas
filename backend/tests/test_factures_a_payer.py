"""Factures à payer (demande de Fred, 20/11/2026, après les impayés EDF et assurance).

- une dépense saisie « à payer » (échéance facultative) compte dans les charges, pas dans la banque ;
- « Marquer payée » : par la copropriété à la date du paiement (la banque la voit à cette date), ou par une
  personne de sa poche (elle devient une avance : justificatif obligatoire) ;
- la liste des factures à payer, en retard d'abord ; e-mail aux syndics 7 jours avant l'échéance, puis une
  fois l'échéance passée (une seule fois chacun).
"""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.document import Document
from app.models.mouvement import Mouvement
from app.services import drive_sauvegarde, factures, reprise
from tests.conftest import auth

AUJ = date.today()
Y = AUJ.year


@pytest.fixture()
def boite(monkeypatch):
    envois = []
    monkeypatch.setattr(drive_sauvegarde, "config_smtp", lambda copro: SimpleNamespace(source="instance"))
    monkeypatch.setattr(drive_sauvegarde, "envoyer_email",
                        lambda copro, dest, sujet, corps: envois.append((dest, sujet, corps)))
    return envois


def _exercice(client, token):
    return client.post("/api/exercices", json={"annee": Y}, headers=auth(token)).json()["id"]


def _facture(client, token, ex_id, **champs):
    corps = {"date": f"{Y}-01-10", "libelle": "Assurance immeuble", "type": "depense", "categorie": "assurance",
             "montant": 612, "a_payer": True, "echeance": str(AUJ + timedelta(days=30)), **champs}
    return client.post(f"/api/exercices/{ex_id}/mouvements", json=corps, headers=auth(token))


def _recap(client, token):
    return client.get("/api/recap", headers=auth(token)).json()


def test_a_payer_puis_payee_par_la_copropriete(client, db, copro_a, syndic_a, token_a):
    ex_id = _exercice(client, token_a)
    r = _facture(client, token_a, ex_id)
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["a_payer"] is True and m["echeance"] == str(AUJ + timedelta(days=30))
    recap = _recap(client, token_a)
    assert (recap["depense"], recap["solde_caisse"], recap["tresorerie_syndicat"]) == (612, 0, 0)
    [f] = client.get("/api/factures-a-payer", headers=auth(token_a)).json()
    assert (f["id"], f["en_retard"]) == (m["id"], False)
    # Payée le 15 février : la banque la voit en février, pas à la date de la facture (janvier).
    r = client.post(f"/api/mouvements/{m['id']}/payer", json={"date": f"{Y}-02-15"}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert (r.json()["a_payer"], r.json()["paye_le"], r.json()["hors_banque"]) == (False, f"{Y}-02-15", False)
    assert _recap(client, token_a)["tresorerie_syndicat"] == -612
    assert reprise._flux(db, copro_a.id, None, date(Y, 1, 31))["syndicat"]["depense"] == 0
    assert reprise._flux(db, copro_a.id, date(Y, 1, 31), date(Y, 2, 28))["syndicat"]["depense"] == 612
    assert client.get("/api/factures-a-payer", headers=auth(token_a)).json() == []
    # Déjà payée ; une date de paiement avant la facture.
    assert client.post(f"/api/mouvements/{m['id']}/payer", json={"date": f"{Y}-02-16"},
                       headers=auth(token_a)).status_code == 409
    m2 = _facture(client, token_a, ex_id).json()
    assert client.post(f"/api/mouvements/{m2['id']}/payer", json={"date": f"{Y}-01-01"},
                       headers=auth(token_a)).status_code == 422


def test_payee_par_une_personne_devient_une_avance(client, db, copro_a, syndic_a, token_a):
    ex_id = _exercice(client, token_a)
    m = _facture(client, token_a, ex_id).json()
    r = client.post(f"/api/mouvements/{m['id']}/payer", json={"date": str(AUJ), "avance_par_id": syndic_a.id},
                    headers=auth(token_a))
    assert r.status_code == 422 and "justificatif" in r.json()["detail"]
    db.expire_all()
    assert db.get(Mouvement, m["id"]).a_payer is True                         # rien n'a changé
    doc = Document(copropriete_id=copro_a.id, categorie="facture", libelle="Assurance", fichier="a.pdf",
                   date_ajout=AUJ)
    db.add(doc)
    db.commit()
    corps = {"date": f"{Y}-01-10", "libelle": "Assurance immeuble", "type": "depense", "categorie": "assurance",
             "montant": 612, "a_payer": True, "echeance": None, "document_id": doc.id}
    assert client.put(f"/api/mouvements/{m['id']}", json=corps, headers=auth(token_a)).status_code == 200
    r = client.post(f"/api/mouvements/{m['id']}/payer", json={"date": str(AUJ), "avance_par_id": syndic_a.id},
                    headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert (r.json()["a_payer"], r.json()["hors_banque"], r.json()["avance_par_id"]) == (False, True, syndic_a.id)
    [p] = client.get("/api/avances", headers=auth(token_a)).json()
    assert p["reste"] == 612
    assert _recap(client, token_a)["tresorerie_syndicat"] == 0


def test_regles(client, db, copro_a, syndic_a, token_a):
    ex_id = _exercice(client, token_a)
    for champs in ({"type": "encaissement"}, {"categorie": "avance", "avance_par_id": syndic_a.id},
                   {"avance_par_id": syndic_a.id}):
        r = _facture(client, token_a, ex_id, **champs)
        assert r.status_code == 422 and "À payer" in r.json()["detail"], champs
    m = _facture(client, token_a, ex_id).json()
    r = client.post("/api/mouvements/groupe", json={"ids": [m["id"]], "type": "encaissement"}, headers=auth(token_a))
    assert r.status_code == 422 and "un par un" in r.json()["detail"]
    # Une dépense ordinaire n'a pas d'échéance ; on ne « paie » pas une dépense déjà réglée.
    r = _facture(client, token_a, ex_id, a_payer=False)
    assert r.json()["echeance"] is None
    assert client.post(f"/api/mouvements/{r.json()['id']}/payer", json={"date": str(AUJ)},
                       headers=auth(token_a)).status_code == 409


def test_rappels_aux_syndics(client, db, copro_a, syndic_a, token_a, boite):
    ex_id = _exercice(client, token_a)
    bientot = _facture(client, token_a, ex_id, libelle="EDF", echeance=str(AUJ + timedelta(days=5))).json()
    _facture(client, token_a, ex_id, libelle="Plus tard", echeance=str(AUJ + timedelta(days=20)))
    retard = _facture(client, token_a, ex_id, libelle="Assurance", echeance=str(AUJ - timedelta(days=1))).json()
    _facture(client, token_a, ex_id, libelle="Sans échéance", echeance=None)
    assert factures.run_rappels(db) == {"avant": 1, "retard": 1}
    assert len(boite) == 2 and all(d == "syndic.a@test.fr" for d, _, _ in boite)
    avant = next(c for _, s, c in boite if "à payer bientôt" in s)
    en_retard = next(c for _, s, c in boite if "en retard de paiement" in s)
    assert "EDF" in avant and "Assurance" in en_retard and "Plus tard" not in avant + en_retard
    # Une seule fois chacun.
    assert factures.run_rappels(db) == {"avant": 0, "retard": 0}
    # L'échéance passe sans paiement : un rappel « en retard », un seul.
    assert factures.run_rappels(db, datetime.now() + timedelta(days=6)) == {"avant": 0, "retard": 1}
    # La liste met le retard en tête.
    liste = client.get("/api/factures-a-payer", headers=auth(token_a)).json()
    assert [f["id"] for f in liste][:2] == [retard["id"], bientot["id"]] and liste[0]["en_retard"]


def test_grand_livre(client, db, copro_a, syndic_a, token_a):
    ex_id = _exercice(client, token_a)
    m = _facture(client, token_a, ex_id, echeance=f"{Y}-12-31").json()
    texte = client.get("/api/export/compte-gestion", headers=auth(token_a)).content.decode("utf-8-sig")
    assert f"à payer (échéance le 31/12/{Y})" in texte
    client.post(f"/api/mouvements/{m['id']}/payer", json={"date": str(AUJ)}, headers=auth(token_a))
    texte = client.get("/api/export/compte-gestion", headers=auth(token_a)).content.decode("utf-8-sig")
    assert f"payée le {AUJ:%d/%m/%Y}" in texte


def test_migration(tmp_path):
    from alembic import command
    from sqlalchemy import create_engine, inspect
    from app import demarrage
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = demarrage.config_alembic(url)
    command.upgrade(cfg, "head")
    assert "a_payer" in [c["name"] for c in inspect(create_engine(url)).get_columns("mouvements")]
    command.downgrade(cfg, "f2a3b4c5d6e7")
    assert "a_payer" not in [c["name"] for c in inspect(create_engine(url)).get_columns("mouvements")]
    command.upgrade(cfg, "head")
