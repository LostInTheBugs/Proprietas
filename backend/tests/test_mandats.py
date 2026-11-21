"""Mandats du syndic bénévole et du conseil syndical (demande de Fred, 21/11/2026).

- une résolution « désignation du syndic » ou « élection du conseil syndical » adoptée enregistre le mandat
  (du jour de l'AG, pour la durée votée : 3 ans au plus — décret n° 67-223, art. 22 et 28) ;
- le mandat suit l'AG (date modifiée, recalcul rejeté, AG supprimée) ;
- un mandat passé se saisit à la main (date seule, ou rattaché à une AG) ;
- échéance : alerte six mois avant, et résolution cochée dans les résolutions types de l'AG annuelle.
"""
import calendar
from datetime import date, timedelta

from tests.conftest import auth
from tests.test_ag_presences import _immeuble


def _plus_mois(d: date, mois: int) -> date:
    a, m = divmod(d.month - 1 + mois, 12)
    an, mo = d.year + a, m + 1
    return date(an, mo, min(d.day, calendar.monthrange(an, mo)[1]))


def _fin(debut: date, mois: int) -> date:
    return _plus_mois(debut, mois) - timedelta(days=1)


def _ag_passee(client, token, jour):
    r = client.post("/api/ag", json={"date": str(jour), "statut": "terminee"}, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _voter(client, token, db, rid, ag_id, membres, voix):
    from app.models.ag import AG
    for u, v in zip(membres, voix):
        lot = next(l for l in db.get(AG, ag_id).copropriete.lots if l.proprietaire_id == u.id)
        client.post(f"/api/resolutions/{rid}/votes", json={"lot_id": lot.id, "voix": v}, headers=auth(token))
    return client.post(f"/api/resolutions/{rid}/calculer", headers=auth(token)).json()


def _mandats(client, token):
    r = client.get("/api/mandats", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def test_mandat_vote_en_ag(client, db, copro_a, syndic_a, token_a):
    marie, paul = _immeuble(db, copro_a, syndic_a, [450, 450])
    jour = date.today() - timedelta(days=10)
    ag_id = _ag_passee(client, token_a, jour)
    corps = {"libelle": "Désignation du syndic bénévole", "nature": "syndic", "majorite": "art25",
             "mandat_mois": 36, "mandat_personnes": [syndic_a.id]}
    r = client.post(f"/api/ag/{ag_id}/resolutions", json=corps, headers=auth(token_a))
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    assert r.json()["mandat_mois"] == 36 and r.json()["mandat_personnes"] == [syndic_a.id]
    assert _mandats(client, token_a)["syndic"]["actuel"] is None              # pas encore votée
    assert _voter(client, token_a, db, rid, ag_id, [marie, paul], ["pour", "pour"])["statut"] == "adoptee"
    s = _mandats(client, token_a)["syndic"]
    assert s["etat"] == "en_cours"
    a = s["actuel"]
    assert (a["debut"], a["fin"]) == (str(jour), str(_fin(jour, 36)))
    assert a["ag_id"] == ag_id and a["resolution_id"] == rid and a["manuel"] is False
    assert [m["personne_id"] for m in a["membres"]] == [syndic_a.id]
    # Un mandat voté en AG ne se supprime pas à la main : il suit la résolution.
    assert client.delete(f"/api/mandats/{a['id']}", headers=auth(token_a)).status_code == 409
    # L'AG change de date : le mandat aussi.
    veille = jour - timedelta(days=1)
    client.put(f"/api/ag/{ag_id}", json={"date": str(veille), "statut": "terminee"}, headers=auth(token_a))
    assert _mandats(client, token_a)["syndic"]["actuel"]["debut"] == str(veille)
    # Recalcul rejeté : le mandat disparaît ; de nouveau adoptée : il revient.
    assert _voter(client, token_a, db, rid, ag_id, [paul], ["contre"])["statut"] == "rejetee"
    s = _mandats(client, token_a)["syndic"]
    assert s["actuel"] is None and s["etat"] == "aucun" and s["historique"] == []
    assert _voter(client, token_a, db, rid, ag_id, [paul], ["pour"])["statut"] == "adoptee"
    assert _mandats(client, token_a)["syndic"]["actuel"] is not None
    # Durée changée sur la résolution adoptée : résultat à recalculer, mandat retiré.
    r = client.put(f"/api/resolutions/{rid}", json={**corps, "mandat_mois": 24}, headers=auth(token_a))
    assert r.json()["statut"] == "a_voter" and _mandats(client, token_a)["syndic"]["actuel"] is None
    assert _voter(client, token_a, db, rid, ag_id, [], [])["statut"] == "adoptee"
    assert _mandats(client, token_a)["syndic"]["actuel"]["fin"] == str(_fin(veille, 24))
    # AG supprimée : plus de mandat.
    assert client.delete(f"/api/ag/{ag_id}", headers=auth(token_a)).status_code == 200
    assert _mandats(client, token_a)["syndic"]["actuel"] is None


def test_resolution_controles_et_second_vote(client, db, copro_a, syndic_a, token_a, token_b):
    marie, paul = _immeuble(db, copro_a, syndic_a, [450, 450])
    ag_id = _ag_passee(client, token_a, date.today() - timedelta(days=3))
    base = {"libelle": "Conseil syndical", "nature": "conseil", "majorite": "art25"}
    url = f"/api/ag/{ag_id}/resolutions"
    assert client.post(url, json={**base, "mandat_mois": 37, "mandat_personnes": [marie.id]},
                       headers=auth(token_a)).status_code == 422                       # 3 ans au plus
    assert client.post(url, json={**base, "nature": "syndic", "mandat_mois": 12, "mandat_personnes": [marie.id, paul.id]},
                       headers=auth(token_a)).status_code == 422                       # un seul syndic
    assert client.post(url, json={**base, "mandat_mois": 12, "mandat_personnes": [99999]},
                       headers=auth(token_a)).status_code == 422                       # pas de la copropriété
    r = client.post(url, json={**base, "mandat_mois": 24, "mandat_personnes": [marie.id, paul.id]}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    # Art. 25 manqué (450 sur 1 000) mais au moins un tiers : second vote à l'art. 24, qui reprend le mandat.
    assert _voter(client, token_a, db, rid, ag_id, [marie, paul], ["pour", "abstention"])["statut"] == "rejetee"
    sv = client.post(f"/api/resolutions/{rid}/second-vote", headers=auth(token_a)).json()
    assert sv["nature"] == "conseil" and sv["mandat_mois"] == 24 and sv["mandat_personnes"] == [marie.id, paul.id]
    assert _voter(client, token_a, db, sv["id"], ag_id, [marie, paul], ["pour", "abstention"])["statut"] == "adoptee"
    c = _mandats(client, token_a)["conseil"]["actuel"]
    assert c["resolution_id"] == sv["id"] and sorted(m["personne_id"] for m in c["membres"]) == sorted([marie.id, paul.id])
    assert client.get("/api/mandats", headers=auth(token_b)).json()["conseil"]["actuel"] is None   # autre copro


def test_mandat_saisi_a_la_main_et_droits(client, db, copro_a, syndic_a, token_a, token_b):
    marie, paul = _immeuble(db, copro_a, syndic_a, [450, 450])
    debut = date.today() - timedelta(days=400)
    corps = {"role": "conseil", "debut": str(debut), "mois": 36, "personne_ids": [marie.id], "noms": ["Jean Dupont"]}
    for mauvais in ({"mois": 37}, {"personne_ids": [99999]}, {"role": "tresorier"}, {"personne_ids": [], "noms": []},
                    {"debut": str(date.today() + timedelta(days=1))}):
        assert client.post("/api/mandats", json={**corps, **mauvais}, headers=auth(token_a)).status_code == 422, mauvais
    r = client.post("/api/mandats", json=corps, headers=auth(token_a))
    assert r.status_code == 200, r.text
    c = _mandats(client, token_a)["conseil"]
    assert c["etat"] == "en_cours" and c["actuel"]["manuel"] is True and c["actuel"]["ag_id"] is None
    assert c["actuel"]["fin"] == str(_fin(debut, 36))
    assert [m["nom"] for m in c["actuel"]["membres"]][1] == "Jean Dupont"
    # Rattaché à une AG de l'application : sa date est reprise.
    ag_id = _ag_passee(client, token_a, date.today() - timedelta(days=30))
    r = client.post("/api/mandats", json={"role": "syndic", "ag_id": ag_id, "mois": 12, "personne_ids": [syndic_a.id]},
                    headers=auth(token_a))
    assert r.status_code == 200, r.text
    s = _mandats(client, token_a)["syndic"]["actuel"]
    assert s["debut"] == str(date.today() - timedelta(days=30)) and s["ag_id"] == ag_id
    # Droits : un copropriétaire consulte, ne saisit pas ; autre copropriété : 404.
    from app.core.security import create_access_token
    t_marie = create_access_token(marie.id, copro_a.id)
    assert client.get("/api/mandats", headers=auth(t_marie)).status_code == 200
    assert client.post("/api/mandats", json=corps, headers=auth(t_marie)).status_code == 403
    mid = c["actuel"]["id"]
    assert client.delete(f"/api/mandats/{mid}", headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/mandats/{mid}", headers=auth(token_a)).status_code == 200
    assert _mandats(client, token_a)["conseil"]["actuel"] is None


def test_echeance_alertes_et_resolutions_types(client, db, copro_a, syndic_a, token_a):
    _immeuble(db, copro_a, syndic_a, [500])
    debut_syndic = _plus_mois(date.today(), -34)                         # fin dans deux mois
    client.post("/api/mandats", json={"role": "syndic", "debut": str(debut_syndic), "mois": 36,
                                      "personne_ids": [syndic_a.id]}, headers=auth(token_a))
    client.post("/api/mandats", json={"role": "conseil", "debut": str(_plus_mois(date.today(), -48)), "mois": 36,
                                      "noms": ["Ancien membre"]}, headers=auth(token_a))
    m = _mandats(client, token_a)
    assert m["syndic"]["etat"] == "bientot" and m["conseil"]["etat"] == "echu"
    assert m["conseil"]["actuel"] is None and len(m["conseil"]["historique"]) == 1
    assert len(m["alertes"]) == 2 and any("syndic" in a for a in m["alertes"])
    fin = _fin(debut_syndic, 36)
    modele = {x["code"]: x for x in client.get(f"/api/ag/modele-annuelle?jour={date.today()}",
                                                headers=auth(token_a)).json()}
    assert modele["syndic"]["coche"] is True and modele["syndic"]["nature"] == "syndic"
    assert f"{fin:%d/%m/%Y}" in modele["syndic"]["remarque"]
    assert modele["conseil"]["coche"] is True and modele["conseil"]["nature"] == "conseil"


def test_sauvegarde_renumerote_les_membres(client, db, copro_a, syndic_a, token_a, token_b):
    from app.models.ag import Resolution
    from app.models.mandat import Mandat
    marie, = _immeuble(db, copro_a, syndic_a, [500])
    client.post("/api/mandats", json={"role": "conseil", "debut": str(date.today() - timedelta(days=30)), "mois": 36,
                                      "personne_ids": [marie.id], "noms": ["Jean Dupont"]}, headers=auth(token_a))
    ag_id = _ag_passee(client, token_a, date.today() - timedelta(days=2))
    client.post(f"/api/ag/{ag_id}/resolutions", json={"libelle": "Syndic", "nature": "syndic", "majorite": "art25",
                                                      "mandat_mois": 12, "mandat_personnes": [marie.id]},
                headers=auth(token_a))
    r = client.post("/api/sauvegarde/export", json={"donnees_personnelles": False, "fichiers": False},
                    headers=auth(token_a))
    assert r.status_code == 200, r.text
    r = client.post("/api/sauvegarde/import", files={"fichier": ("s.zip", r.content, "application/zip")},
                    data={"mot_de_passe": ""}, headers=auth(token_b))
    assert r.status_code == 200, r.text
    nid = r.json()["copropriete_id"]
    m = db.query(Mandat).filter(Mandat.copropriete_id == nid).one()
    nouveau = m.membres[0]["personne_id"]
    assert nouveau not in (None, marie.id) and m.membres[1] == {"personne_id": None, "nom": ""}   # sans données perso
    res = db.query(Resolution).join(Resolution.ag).filter(Resolution.nature == "syndic", Resolution.ag_id != ag_id).one()
    assert res.mandat_personnes == [nouveau]
