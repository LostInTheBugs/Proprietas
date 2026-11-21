"""Vote en direct pendant l'AG (demande de Fred, 21/11/2026).

- le syndic ouvre le vote d'une résolution à la fois, puis le clôt : le résultat est alors calculé (majorité) ;
- votent depuis leur compte les copropriétaires présents ou en visioconférence, pour leurs lots et ceux de leurs
  mandants (pouvoirs) ; seulement les lots de la clé quand la résolution en a une ;
- tant que le vote est ouvert, chacun peut changer son vote ; tout le monde voit le décompte ;
- le syndic peut toujours saisir les votes à la main.
"""
from datetime import date, timedelta

from app.core.security import create_access_token
from app.models.ag import AG, Vote
from app.models.audit import AuditLog
from tests.conftest import auth
from tests.test_ag_presences import _immeuble, _repondre


def _ag_du_jour(client, token, lien=True):
    r = client.post("/api/ag", json={"date": str(date.today()), "heure": "18:30", "statut": "convoquee"},
                    headers=auth(token))
    ag_id = r.json()["id"]
    if lien:
        client.post(f"/api/ag/{ag_id}/lien-jitsi", headers=auth(token))
    return ag_id


def _res(client, token, ag_id, libelle="Ravalement", **extra):
    r = client.post(f"/api/ag/{ag_id}/resolutions", json={"libelle": libelle, "majorite": "art24", **extra},
                    headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _tok(u, copro):
    return create_access_token(u.id, copro.id)


def test_vote_en_direct(client, db, copro_a, syndic_a, token_a):
    marie, paul, jean = _immeuble(db, copro_a, syndic_a, [300, 300, 300])
    ag_id = _ag_du_jour(client, token_a)
    r1 = _res(client, token_a, ag_id)
    r2 = _res(client, token_a, ag_id, "Interphone")
    _repondre(client, ag_id, marie, copro_a, reponse="visio")
    _repondre(client, ag_id, paul, copro_a, reponse="present")
    _repondre(client, ag_id, jean, copro_a, reponse="absent")
    url = f"/api/ag/{ag_id}/vote-en-ligne"
    # Rien d'ouvert : on ne vote pas.
    assert client.get(url, headers=auth(_tok(marie, copro_a))).json()["resolution"] is None
    assert client.put(f"/api/resolutions/{r1}/mon-vote", json={"voix": "pour"},
                      headers=auth(_tok(marie, copro_a))).status_code == 409
    r = client.post(f"/api/resolutions/{r1}/vote-en-ligne/ouvrir", headers=auth(token_a))
    assert r.status_code == 200, r.text
    # Une seule résolution à la fois.
    assert client.post(f"/api/resolutions/{r2}/vote-en-ligne/ouvrir", headers=auth(token_a)).status_code == 409
    e = client.get(url, headers=auth(_tok(marie, copro_a))).json()
    assert e["resolution"]["id"] == r1 and e["peut_voter"] is True
    assert [(l["numero"], l["au_titre"], l["voix"]) for l in e["mes_lots"]] == [("1", "", None)]
    # Marie (visio) pour, Paul (présent) contre puis pour ; Jean (absent) ne vote pas.
    assert client.put(f"/api/resolutions/{r1}/mon-vote", json={"voix": "pour"},
                      headers=auth(_tok(marie, copro_a))).status_code == 200
    client.put(f"/api/resolutions/{r1}/mon-vote", json={"voix": "contre"}, headers=auth(_tok(paul, copro_a)))
    r = client.put(f"/api/resolutions/{r1}/mon-vote", json={"voix": "pour"}, headers=auth(_tok(paul, copro_a)))
    assert r.status_code == 200 and r.json()["mes_lots"][0]["voix"] == "pour"
    assert client.get(url, headers=auth(_tok(jean, copro_a))).json()["peut_voter"] is False
    assert client.put(f"/api/resolutions/{r1}/mon-vote", json={"voix": "contre"},
                      headers=auth(_tok(jean, copro_a))).status_code == 403
    assert client.put(f"/api/resolutions/{r1}/mon-vote", json={"voix": "peut-être"},
                      headers=auth(_tok(marie, copro_a))).status_code == 422
    # Décompte visible de tous, en direct.
    d = client.get(url, headers=auth(_tok(jean, copro_a))).json()["decompte"]
    assert (d["pour"], d["contre"], d["votants"]) == (600, 0, 2)
    assert db.query(Vote).filter(Vote.resolution_id == r1, Vote.voix == "pour").count() == 2
    assert db.query(AuditLog).filter(AuditLog.action == "vote_en_ligne").count() == 3
    # Clôture : résultat calculé ; plus de vote ensuite.
    r = client.post(f"/api/resolutions/{r1}/vote-en-ligne/clore", headers=auth(token_a))
    assert r.status_code == 200 and r.json()["statut"] == "adoptee"
    assert client.get(url, headers=auth(_tok(marie, copro_a))).json()["resolution"] is None
    assert client.put(f"/api/resolutions/{r1}/mon-vote", json={"voix": "contre"},
                      headers=auth(_tok(marie, copro_a))).status_code == 409
    # La résolution suivante peut maintenant s'ouvrir.
    assert client.post(f"/api/resolutions/{r2}/vote-en-ligne/ouvrir", headers=auth(token_a)).status_code == 200


def test_pouvoirs_et_cle(client, db, copro_a, syndic_a, token_a):
    marie, paul, anne = _immeuble(db, copro_a, syndic_a, [300, 300, 300])
    ag_id = _ag_du_jour(client, token_a, lien=False)
    _repondre(client, ag_id, marie, copro_a, reponse="present")
    _repondre(client, ag_id, anne, copro_a, reponse="pouvoir", mandataire_id=marie.id)
    r1 = _res(client, token_a, ag_id)
    client.post(f"/api/resolutions/{r1}/vote-en-ligne/ouvrir", headers=auth(token_a))
    t_marie = _tok(marie, copro_a)
    lots = client.get(f"/api/ag/{ag_id}/vote-en-ligne", headers=auth(t_marie)).json()["mes_lots"]
    assert [(l["numero"], l["au_titre"]) for l in lots] == [("1", ""), ("3", "pouvoir de Membre c3@exemple.fr")]
    # Un vote pour tous ses lots, puis un autre pour le seul lot de sa mandante.
    client.put(f"/api/resolutions/{r1}/mon-vote", json={"voix": "pour"}, headers=auth(t_marie))
    lot_anne = lots[1]["lot_id"]
    r = client.put(f"/api/resolutions/{r1}/mon-vote", json={"voix": "contre", "lot_ids": [lot_anne]}, headers=auth(t_marie))
    assert [l["voix"] for l in r.json()["mes_lots"]] == ["pour", "contre"]
    autre = next(l.id for l in db.get(AG, ag_id).copropriete.lots if l.proprietaire_id == paul.id)
    assert client.put(f"/api/resolutions/{r1}/mon-vote", json={"voix": "pour", "lot_ids": [autre]},
                      headers=auth(t_marie)).status_code == 422                   # pas son lot
    client.post(f"/api/resolutions/{r1}/vote-en-ligne/clore", headers=auth(token_a))
    # Résolution sur une clé dont le lot de Marie est exclu : elle ne vote que pour sa mandante.
    lot_marie = lots[0]["lot_id"]
    cle = client.post("/api/cles", json={"nom": "Escalier B", "lots": [{"lot_id": lot_anne, "tantiemes": 100},
                                                                       {"lot_id": autre, "tantiemes": 100}]},
                      headers=auth(token_a))
    assert cle.status_code == 200, cle.text
    cle_id = next(c["id"] for c in cle.json() if c["nom"] == "Escalier B")
    r2 = _res(client, token_a, ag_id, "Escalier", cle_id=cle_id)
    client.post(f"/api/resolutions/{r2}/vote-en-ligne/ouvrir", headers=auth(token_a))
    lots = client.get(f"/api/ag/{ag_id}/vote-en-ligne", headers=auth(t_marie)).json()["mes_lots"]
    assert [l["lot_id"] for l in lots] == [lot_anne]
    assert client.put(f"/api/resolutions/{r2}/mon-vote", json={"voix": "pour", "lot_ids": [lot_marie]},
                      headers=auth(t_marie)).status_code == 422


def test_ouverture_droits_et_dates(client, db, copro_a, syndic_a, token_a, token_b):
    marie, = _immeuble(db, copro_a, syndic_a, [500])
    futur = client.post("/api/ag", json={"date": str(date.today() + timedelta(days=5))}, headers=auth(token_a)).json()["id"]
    rf = _res(client, token_a, futur)
    assert client.post(f"/api/resolutions/{rf}/vote-en-ligne/ouvrir", headers=auth(token_a)).status_code == 422
    ag_id = _ag_du_jour(client, token_a)
    r1 = _res(client, token_a, ag_id)
    assert client.post(f"/api/resolutions/{r1}/vote-en-ligne/ouvrir", headers=auth(_tok(marie, copro_a))).status_code == 403
    assert client.post(f"/api/resolutions/{r1}/vote-en-ligne/ouvrir", headers=auth(token_b)).status_code == 404
    assert client.get(f"/api/ag/{ag_id}/vote-en-ligne", headers=auth(token_b)).status_code == 404
    assert client.post(f"/api/resolutions/{r1}/vote-en-ligne/clore", headers=auth(token_a)).status_code == 409  # pas ouvert
    # La résolution affiche son état de vote en ligne.
    client.post(f"/api/resolutions/{r1}/vote-en-ligne/ouvrir", headers=auth(token_a))
    res = next(x for a in client.get("/api/ag", headers=auth(token_a)).json() for x in a["resolutions"] if x["id"] == r1)
    assert res["vote_en_ligne"] == "ouvert"
    # Supprimer la résolution ouverte libère l'AG.
    assert client.delete(f"/api/resolutions/{r1}", headers=auth(token_a)).status_code == 200
    r2 = _res(client, token_a, ag_id, "Autre")
    assert client.post(f"/api/resolutions/{r2}/vote-en-ligne/ouvrir", headers=auth(token_a)).status_code == 200
