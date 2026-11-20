"""Messages groupés du syndic aux copropriétaires (demande de Fred, 20/11/2026) : tous, une clé ou une sélection ;
un e-mail par personne, personnalisé ; information (pied du message) ; historique ; réservé au syndic."""
from types import SimpleNamespace

import pytest

from app.models.cle import CleLot, CleRepartition
from app.models.lot import Lot
from app.services import emailer
from tests.conftest import auth
from tests.test_ag_presences import _immeuble


@pytest.fixture()
def boite(monkeypatch):
    envois = []
    monkeypatch.setattr(emailer, "config_smtp", lambda copro: SimpleNamespace(source="instance"))

    def envoyer(copro, dest, sujet, corps):
        if dest.startswith("c3@"):
            raise emailer.EmailError("boîte pleine")
        envois.append((dest, sujet, corps))
    monkeypatch.setattr(emailer, "envoyer_email", envoyer)
    return envois


def _msg(**k):
    return {"sujet": "Coupure d'eau {lots}", "corps": "Bonjour {prenom} {nom},\nCoupure jeudi.", **k}


def test_tous_personnalise_et_historique(client, db, copro_a, syndic_a, token_a, boite):
    a, b, c = _immeuble(db, copro_a, syndic_a, [300, 300, 300])
    r = client.post("/api/messages/apercu", json=_msg(), headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert len(r.json()["destinataires"]) == 4 and "Lot" not in r.json()["exemple"]["sujet"]
    assert "pas une convocation" in r.json()["exemple"]["corps"]
    r = client.post("/api/messages", json=_msg(), headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert r.json()["nb_envoyes"] == 3 and r.json()["erreurs"] == ["Membre c3@exemple.fr : boîte pleine"]
    envoi = next(e for e in boite if e[0] == "c1@exemple.fr")
    assert envoi[1] == "Coupure d'eau 1" and "Bonjour" in envoi[2] and "{prenom}" not in envoi[2]
    h = client.get("/api/messages", headers=auth(token_a)).json()
    assert len(h) == 1 and h[0]["nb_envoyes"] == 3 and len(h[0]["destinataires"]) == 4


def test_cle_selection_et_controles(client, db, copro_a, syndic_a, token_a, token_b, boite):
    a, b, c = _immeuble(db, copro_a, syndic_a, [300, 300, 300])
    lots = {l.proprietaire_id: l for l in db.query(Lot).filter(Lot.copropriete_id == copro_a.id)}
    cle = CleRepartition(copropriete_id=copro_a.id, nom="Ascenseur")
    db.add(cle)
    db.flush()
    db.add_all([CleLot(cle_id=cle.id, lot_id=lots[a.id].id, tantiemes=600), CleLot(cle_id=cle.id, lot_id=lots[b.id].id, tantiemes=400)])
    db.commit()
    r = client.post("/api/messages", json=_msg(cible="cle", cle_id=cle.id), headers=auth(token_a))
    assert r.json()["nb_envoyes"] == 2 and sorted(e[0] for e in boite) == ["c1@exemple.fr", "c2@exemple.fr"]
    boite.clear()
    r = client.post("/api/messages", json=_msg(cible="selection", ids=[b.id]), headers=auth(token_a))
    assert [e[0] for e in boite] == ["c2@exemple.fr"]
    assert client.post("/api/messages", json=_msg(cible="selection", ids=[99999]), headers=auth(token_a)).status_code == 422
    assert client.post("/api/messages", json=_msg(sujet=" "), headers=auth(token_a)).status_code == 422
    assert client.post("/api/messages", json=_msg(cible="cle", cle_id=None), headers=auth(token_a)).status_code == 422
    from app.core.security import create_access_token
    assert client.post("/api/messages", json=_msg(), headers=auth(create_access_token(a.id, copro_a.id))).status_code == 403
    assert client.get("/api/messages", headers=auth(token_b)).json() == []


def test_sans_serveur_d_envoi(client, db, copro_a, syndic_a, token_a, monkeypatch):
    _immeuble(db, copro_a, syndic_a, [500])
    monkeypatch.setattr(emailer, "config_smtp", lambda copro: None)
    r = client.post("/api/messages", json=_msg(), headers=auth(token_a))
    assert r.status_code == 422 and "serveur d'envoi" in r.json()["detail"]
