"""Résolution sur une clé de répartition (loi 1965, art. 24, dernier alinéa ; demande de Fred, 20/11/2026) : seuls les
copropriétaires concernés votent, avec leurs millièmes de la clé ; les votes des autres lots ne comptent pas."""
import io

from pypdf import PdfReader

from app.models.cle import CleLot, CleRepartition
from app.models.lot import Lot
from tests.conftest import auth
from tests.test_ag_presences import _ag, _immeuble


def _cle(db, copro, parts):
    c = CleRepartition(copropriete_id=copro.id, nom="Ascenseur")
    db.add(c)
    db.flush()
    for lot, t in parts:
        db.add(CleLot(cle_id=c.id, lot_id=lot.id, tantiemes=t))
    db.commit()
    return c


def _voter(client, token, rid, lot, voix):
    assert client.post(f"/api/resolutions/{rid}/votes", json={"lot_id": lot.id, "voix": voix},
                       headers=auth(token)).status_code == 200


def test_seuls_les_lots_de_la_cle_votent(client, db, copro_a, syndic_a, token_a):
    a, b, c = _immeuble(db, copro_a, syndic_a, [300, 300, 300])
    l = {x.proprietaire_id: x for x in db.query(Lot).filter(Lot.copropriete_id == copro_a.id)}
    cle = _cle(db, copro_a, [(l[a.id], 700), (l[b.id], 300)])                # c n'est pas concerné
    ag_id = _ag(client, token_a)
    r = client.post(f"/api/ag/{ag_id}/resolutions", json={"numero": 1, "libelle": "Remplacement de l'ascenseur",
                                                          "majorite": "art25", "cle_id": cle.id}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert (r.json()["cle_id"], r.json()["cle_nom"]) == (cle.id, "Ascenseur")
    rid = r.json()["id"]
    _voter(client, token_a, rid, l[a.id], "pour")                                # 700 / 1 000 de la clé
    _voter(client, token_a, rid, l[c.id], "contre")                              # ignoré : hors de la clé
    res = client.post(f"/api/resolutions/{rid}/calculer", headers=auth(token_a)).json()
    assert (res["resultat"]["pour"], res["resultat"]["contre"], res["resultat"]["total"]) == (700, 0, 1000)
    assert res["statut"] == "adoptee"                                            # art. 25 : > 500 / 1 000
    pv = client.get(f"/api/ag/{ag_id}/pv", headers=auth(token_a))
    t = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pv.content)).pages)
    assert "Ascenseur" in t and "art. 24, dernier" in t.replace("\n", " ")
    # Une clé utilisée par une résolution ne se supprime pas.
    assert client.delete(f"/api/cles/{cle.id}", headers=auth(token_a)).status_code == 409


def test_controles(client, db, copro_a, syndic_a, token_a, copro_b):
    a, b = _immeuble(db, copro_a, syndic_a, [500, 400])
    l = {x.proprietaire_id: x for x in db.query(Lot).filter(Lot.copropriete_id == copro_a.id)}
    cle = _cle(db, copro_a, [(l[a.id], 1000)])
    autre = CleRepartition(copropriete_id=copro_b.id, nom="Ailleurs")
    db.add(autre)
    db.commit()
    ag_id = _ag(client, token_a)
    url = f"/api/ag/{ag_id}/resolutions"
    assert client.post(url, json={"libelle": "Budget", "nature": "budget", "cle_id": cle.id},
                       headers=auth(token_a)).status_code == 422
    assert client.post(url, json={"libelle": "X", "cle_id": autre.id}, headers=auth(token_a)).status_code == 422
    rid = client.post(url, json={"libelle": "X", "majorite": "art25", "cle_id": cle.id}, headers=auth(token_a)).json()["id"]
    # Modifiée sans clé : tous les copropriétaires votent de nouveau.
    _voter(client, token_a, rid, l[a.id], "contre")
    r = client.put(f"/api/resolutions/{rid}", json={"libelle": "X", "majorite": "art24"}, headers=auth(token_a))
    assert r.status_code == 200 and r.json()["cle_id"] is None                  # retirée : tous votent de nouveau
