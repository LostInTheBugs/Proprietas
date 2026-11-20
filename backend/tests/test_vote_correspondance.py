"""Vote par correspondance (demande de Fred, 20/11/2026 ; loi 1965, art. 17-1 A ; décret 1967, art. 9 bis, 14, 14-1).

- formulaire à joindre à la convocation (PDF, un par copropriétaire) ;
- reçu au plus tard trois jours francs avant l'AG (J − 4), sinon refusé ;
- abstention ou case vide : vote défavorable ; « pour » sur une résolution amendée : défaillant ;
- ignoré si le copropriétaire est présent ou représenté ; mentionné sur la feuille de présence.
"""
import io
from datetime import date, timedelta

from pypdf import PdfReader

from app.models.ag import Vote
from tests.conftest import auth
from app.models.lot import Lot
from tests.test_ag_presences import _ag, _immeuble


def _resolution(client, token, ag_id, numero, libelle):
    r = client.post(f"/api/ag/{ag_id}/resolutions", json={"numero": numero, "libelle": libelle, "majorite": "art24"},
                    headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _saisir(client, token, ag_id, personne_id, recu_le, votes):
    return client.put(f"/api/ag/{ag_id}/correspondance/{personne_id}", json={"recu_le": str(recu_le), "votes": votes},
                      headers=auth(token))


def _texte(contenu):
    return " ".join(p.extract_text() for p in PdfReader(io.BytesIO(contenu)).pages).replace("\n", " ")


def test_formulaire_saisie_et_resultat(client, db, copro_a, syndic_a, token_a):
    marie, paul, jean = _immeuble(db, copro_a, syndic_a, [300, 300, 300])
    ag_id = _ag(client, token_a, jours=30)
    r1 = _resolution(client, token_a, ag_id, 1, "Ravalement")
    r2 = _resolution(client, token_a, ag_id, 2, "Interphone")
    pdf = client.get(f"/api/ag/{ag_id}/formulaires-correspondance.pdf", headers=auth(token_a))
    assert pdf.status_code == 200
    t = _texte(pdf.content)
    assert "FORMULAIRE DE VOTE PAR CORRESPONDANCE" in t and "Ravalement" in t and "Interphone" in t
    limite = date.today() + timedelta(days=26)
    assert f"{limite:%d/%m/%Y}" in t
    # Marie : pour / abstention ; Paul : contre / case vide.
    assert _saisir(client, token_a, ag_id, marie.id, date.today(), {r1: "pour", r2: "abstention"}).status_code == 200
    e = _saisir(client, token_a, ag_id, paul.id, date.today(), {r1: "contre"}).json()
    assert e["date_limite"] == str(limite) and [f["nom"] for f in e["formulaires"]] == sorted([f["nom"] for f in e["formulaires"]])
    res = client.post(f"/api/resolutions/{r1}/calculer", headers=auth(token_a)).json()
    assert (res["resultat"]["pour"], res["resultat"]["contre"]) == (300, 300)
    res = client.post(f"/api/resolutions/{r2}/calculer", headers=auth(token_a)).json()
    assert res["resultat"]["contre"] == 600 and res["resultat"]["pour"] == 0        # abstention et vide : contre
    # Feuille de présence et présences.
    p = client.get(f"/api/ag/{ag_id}/presences", headers=auth(token_a)).json()
    assert p["totaux"]["correspondances"] == 2 and p["totaux"]["voix_correspondance"] > 0
    t = _texte(client.get(f"/api/ag/{ag_id}/feuille-presence", headers=auth(token_a)).content)
    assert "Vote par correspondance (formulaire reçu le" in t


def test_amendee_present_retard_et_droits(client, db, copro_a, syndic_a, token_a, token_b):
    marie, paul = _immeuble(db, copro_a, syndic_a, [450, 450])
    ag_id = _ag(client, token_a, jours=10)
    r1 = _resolution(client, token_a, ag_id, 1, "Ravalement")
    # Reçu trop tard : moins de trois jours francs avant l'AG.
    trop_tard = date.today() + timedelta(days=7)
    r = _saisir(client, token_a, ag_id, marie.id, trop_tard, {r1: "pour"})
    assert r.status_code == 422
    assert _saisir(client, token_a, ag_id, marie.id, date.today() + timedelta(days=1), {r1: "pour"}).status_code == 422  # futur
    assert _saisir(client, token_a, ag_id, marie.id, date.today(), {r1: "pour"}).status_code == 200
    assert _saisir(client, token_a, ag_id, paul.id, date.today(), {r1: "pour"}).status_code == 200
    # Résolution amendée : les « pour » par correspondance deviennent défaillants.
    r = client.put(f"/api/resolutions/{r1}/amendee", json={"amendee": True}, headers=auth(token_a))
    assert r.status_code == 200 and r.json()["amendee"] is True
    res = client.post(f"/api/resolutions/{r1}/calculer", headers=auth(token_a)).json()
    assert res["resultat"]["pour"] == 0
    client.put(f"/api/resolutions/{r1}/amendee", json={"amendee": False}, headers=auth(token_a))
    assert client.post(f"/api/resolutions/{r1}/calculer", headers=auth(token_a)).json()["resultat"]["pour"] == 900
    # Paul vient finalement : son formulaire est écarté ; le syndic saisit son vote en séance.
    r = client.put(f"/api/ag/{ag_id}/presences/{paul.id}", json={"reponse": "present"}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    e = client.get(f"/api/ag/{ag_id}/correspondance", headers=auth(token_a)).json()
    assert {f["nom"]: f["ecarte"] for f in e["formulaires"]} == {"Membre c1@exemple.fr": False, "Membre c2@exemple.fr": True}
    # Retrait du formulaire de Marie : ses votes disparaissent.
    assert client.delete(f"/api/ag/{ag_id}/correspondance/{marie.id}", headers=auth(token_a)).status_code == 200
    db.expire_all()
    lot_marie = db.query(Lot).filter(Lot.proprietaire_id == marie.id).one()
    assert db.query(Vote).filter(Vote.resolution_id == r1, Vote.lot_id == lot_marie.id).count() == 0
    # Droits : un copropriétaire ne saisit rien, ne télécharge que son propre formulaire ; autre copro : 404.
    from app.core.security import create_access_token
    t_marie = create_access_token(marie.id, copro_a.id)
    assert _saisir(client, t_marie, ag_id, marie.id, date.today(), {r1: "pour"}).status_code == 403
    t = _texte(client.get(f"/api/ag/{ag_id}/formulaires-correspondance.pdf", headers=auth(t_marie)).content)
    assert "c1@exemple.fr" in t and "c2@exemple.fr" not in t
    assert client.get(f"/api/ag/{ag_id}/correspondance", headers=auth(token_b)).status_code == 404


def test_consultation_ecrite_et_non_coproprietaire(client, db, copro_a, syndic_a, token_a):
    marie, = _immeuble(db, copro_a, syndic_a, [500])
    r = client.post("/api/ag", json={"date": str(date.today() + timedelta(days=30)), "type_ag": "consultation_ecrite"},
                    headers=auth(token_a))
    ag_id = r.json()["id"]
    assert _saisir(client, token_a, ag_id, marie.id, date.today(), {}).status_code == 422
    assert client.get(f"/api/ag/{ag_id}/formulaires-correspondance.pdf", headers=auth(token_a)).status_code == 422
    ag2 = _ag(client, token_a)
    assert _saisir(client, token_a, ag2, 99999, date.today(), {}).status_code == 422
