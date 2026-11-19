"""AG : réponse des copropriétaires et pouvoirs (demande de Fred, 19/11/2026).

Choix de Fred : quatre réponses (« Je serai présent(e) », « … je donne pouvoir à… », « Je ne serai pas
présent(e) », « Je ne sais pas encore ») ; le pouvoir se donne à un autre copropriétaire (compte) ; la
désignation en ligne est enregistrée ET le pouvoir est produit en PDF, à signer.

- réponse par le lien de l'e-mail (formulaire sans script, rien n'est enregistré à l'ouverture) ou depuis le
  compte ; modifiable jusqu'à l'ouverture de l'AG, le syndic corrige à tout moment ;
- art. 22 : jamais le syndic ; au plus trois pouvoirs par mandataire, sauf sous 10 % des voix ;
- le syndic voit le tableau, note « pouvoir signé reçu », télécharge pouvoirs et feuille de présence ; le PV
  indique présents et représentés.
"""
from datetime import date, datetime, timedelta

import pytest

from app.core.config import get_settings
from app.core.security import create_access_token
from app.models.ag import AG, AgReponse
from app.models.lot import Lot
from app.routes import ag as routes_ag
from tests.conftest import _make_membre, auth


@pytest.fixture()
def envois(monkeypatch):
    boite = []
    monkeypatch.setattr(routes_ag, "envoyer_email", lambda copro, dest, sujet, corps: boite.append((dest, corps)))
    monkeypatch.setattr(get_settings(), "frontend_url", "https://copro.exemple.fr/")
    return boite


def _immeuble(db, copro, syndic, tantiemes):
    """Un copropriétaire par lot (tantièmes donnés) ; le syndic possède aussi un lot."""
    db.add(Lot(copropriete_id=copro.id, numero="S", tantiemes=100, proprietaire_id=syndic.id))
    membres = []
    for i, t in enumerate(tantiemes, start=1):
        u = _make_membre(db, f"c{i}@exemple.fr", copro)
        db.add(Lot(copropriete_id=copro.id, numero=str(i), tantiemes=t, proprietaire_id=u.id))
        membres.append(u)
    db.commit()
    return membres


def _ag(client, token, jours=30, heure="18:30"):
    r = client.post("/api/ag", json={"date": str(date.today() + timedelta(days=jours)), "heure": heure},
                    headers=auth(token))
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _repondre(client, ag_id, u, copro, **corps):
    return client.put(f"/api/ag/{ag_id}/ma-reponse", json=corps, headers=auth(create_access_token(u.id, copro.id)))


def test_par_le_lien_de_l_email(client, db, copro_a, syndic_a, token_a, envois):
    marie, paul = _immeuble(db, copro_a, syndic_a, [450, 450])
    ag_id = _ag(client, token_a)
    client.post(f"/api/ag/{ag_id}/invitations", headers=auth(token_a))
    corps = next(c for d, c in envois if d == "c1@exemple.fr")
    assert "présent(e), absent(e) ou représenté(e)" in corps
    lien = next(l for l in corps.splitlines() if "/api/ag/confirmation/" in l).removeprefix("https://copro.exemple.fr")
    page = client.get(lien)
    assert "Serez-vous présent(e) ?" in page.text and "Membre c2@exemple.fr" in page.text
    assert "Syndic syndic.a@test.fr" not in page.text                   # le syndic ne reçoit pas de pouvoir
    assert db.query(AgReponse).count() == 0                            # GET : rien d'enregistré
    merci = client.post(lien, data={"reponse": "pouvoir", "mandataire_id": str(paul.id)})
    assert merci.status_code == 200 and "Réponse enregistrée" in merci.text and "Membre c2@exemple.fr" in merci.text
    assert "/pouvoir" in merci.text
    pdf = client.get(lien + "/pouvoir")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    # Changer d'avis avec le même lien.
    client.post(lien, data={"reponse": "present"})
    [r] = db.query(AgReponse).all()
    assert (r.reponse, r.mandataire_id, r.source) == ("present", None, "lien")
    assert client.get(lien + "/pouvoir").status_code == 404
    # Pouvoir sans mandataire : le formulaire revient avec l'erreur.
    erreur = client.post(lien, data={"reponse": "pouvoir"})
    assert "Choisissez le copropriétaire" in erreur.text


def test_depuis_le_compte_et_tableau_du_syndic(client, db, copro_a, syndic_a, token_a):
    marie, paul, jean = _immeuble(db, copro_a, syndic_a, [300, 300, 300])
    ag_id = _ag(client, token_a)
    moi = client.get(f"/api/ag/{ag_id}/ma-reponse", headers=auth(create_access_token(marie.id, copro_a.id))).json()
    assert moi["coproprietaire"] and moi["ouvert"] and moi["reponse"] == ""
    assert {m["id"] for m in moi["mandataires"]} == {paul.id, jean.id}
    assert _repondre(client, ag_id, marie, copro_a, reponse="pouvoir", mandataire_id=paul.id).status_code == 200
    assert _repondre(client, ag_id, paul, copro_a, reponse="present").json()["mandats"] == [
        {"id": marie.id, "nom": "Membre c1@exemple.fr"}]
    _repondre(client, ag_id, jean, copro_a, reponse="incertain")
    e = client.get(f"/api/ag/{ag_id}/presences", headers=auth(token_a)).json()
    lignes = {l["personne_id"]: l for l in e["lignes"]}
    assert lignes[marie.id]["reponse"] == "pouvoir" and lignes[marie.id]["mandataire_nom"] == "Membre c2@exemple.fr"
    assert lignes[paul.id]["mandats"] == 1 and lignes[syndic_a.id]["reponse"] == ""
    assert e["totaux"] == {"presents": 1, "representes": 1, "absents": 0, "incertains": 1, "sans_reponse": 1,
                           "voix_presentes_ou_representees": 600.0}
    # Pouvoir signé reçu, puis le pouvoir du syndic et la feuille de présence en PDF.
    r = client.put(f"/api/ag/{ag_id}/presences/{marie.id}",
                   json={"reponse": "pouvoir", "mandataire_id": paul.id, "pouvoir_recu": True}, headers=auth(token_a))
    assert r.status_code == 200 and next(l for l in r.json()["lignes"] if l["personne_id"] == marie.id)["pouvoir_recu_le"]
    for chemin in (f"/api/ag/{ag_id}/pouvoirs/{marie.id}", f"/api/ag/{ag_id}/feuille-presence"):
        pdf = client.get(chemin, headers=auth(token_a))
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    # Le mandataire télécharge le pouvoir ; un autre copropriétaire, non.
    assert client.get(f"/api/ag/{ag_id}/pouvoirs/{marie.id}",
                      headers=auth(create_access_token(paul.id, copro_a.id))).status_code == 200
    assert client.get(f"/api/ag/{ag_id}/pouvoirs/{marie.id}",
                      headers=auth(create_access_token(jean.id, copro_a.id))).status_code == 403
    # Changer de mandataire efface « pouvoir signé reçu ».
    _repondre(client, ag_id, marie, copro_a, reponse="pouvoir", mandataire_id=jean.id)
    db.expire_all()
    assert db.query(AgReponse).filter(AgReponse.personne_id == marie.id).one().pouvoir_recu_le is None
    # Le tableau est réservé au syndic.
    assert client.get(f"/api/ag/{ag_id}/presences",
                      headers=auth(create_access_token(jean.id, copro_a.id))).status_code == 403


def test_jamais_le_syndic(client, db, copro_a, syndic_a, token_a):
    [marie] = _immeuble(db, copro_a, syndic_a, [500])
    ag_id = _ag(client, token_a)
    r = _repondre(client, ag_id, marie, copro_a, reponse="pouvoir", mandataire_id=syndic_a.id)
    assert r.status_code == 422 and "art. 22" in r.json()["detail"]
    r = _repondre(client, ag_id, marie, copro_a, reponse="pouvoir", mandataire_id=marie.id)
    assert r.status_code == 422


def test_trois_pouvoirs_sauf_sous_10_pourcent(client, db, copro_a, syndic_a, token_a):
    # 10 copropriétaires : deux « gros » (2000) puis des petits (100 chacun) ; total 100 + 4000 + 800 = 4900.
    membres = _immeuble(db, copro_a, syndic_a, [2000, 2000] + [100] * 8)
    gros1, gros2, *petits = membres
    ag_id = _ag(client, token_a)
    # Mandataire « petit » (100) : trois pouvoirs sans condition de voix ; un quatrième porterait ses voix et celles
    # de ses mandants à 100 + 4 × 100 = 500, plus que 10 % des 4900 voix (490) → refusé.
    mandataire = petits[0]
    for p in petits[1:4]:
        assert _repondre(client, ag_id, p, copro_a, reponse="pouvoir", mandataire_id=mandataire.id).status_code == 200
    r = _repondre(client, ag_id, petits[4], copro_a, reponse="pouvoir", mandataire_id=mandataire.id)
    assert r.status_code == 422 and "10 %" in r.json()["detail"]
    # Un gros copropriétaire peut recevoir 3 pouvoirs même au-delà de 10 % des voix.
    for p in petits[4:7]:
        assert _repondre(client, ag_id, p, copro_a, reponse="pouvoir", mandataire_id=gros1.id).status_code == 200
    # Changer sa propre réponse ne compte pas deux fois.
    assert _repondre(client, ag_id, petits[1], copro_a, reponse="pouvoir", mandataire_id=mandataire.id).status_code == 200


def test_plus_de_reponse_en_ligne_une_fois_l_ag_ouverte(client, db, copro_a, syndic_a, token_a, envois):
    [marie] = _immeuble(db, copro_a, syndic_a, [500])
    ag_id = _ag(client, token_a)
    client.post(f"/api/ag/{ag_id}/invitations", headers=auth(token_a))
    lien = next(l for l in envois[0][1].splitlines() if "/api/ag/confirmation/" in l).removeprefix("https://copro.exemple.fr")
    ag = db.get(AG, ag_id)
    ouverte = datetime.now() - timedelta(hours=1)        # même instant pour la date et l'heure (vrai aussi après minuit)
    ag.date, ag.heure = ouverte.date(), ouverte.strftime("%H:%M")
    db.commit()
    assert _repondre(client, ag_id, marie, copro_a, reponse="present").status_code == 409
    assert "plus possible de répondre" in client.get(lien).text
    assert "plus possible de répondre" in client.post(lien, data={"reponse": "present"}).text
    # Le syndic, lui, tient la feuille de présence en séance.
    r = client.put(f"/api/ag/{ag_id}/presences/{marie.id}", json={"reponse": "present"}, headers=auth(token_a))
    assert r.status_code == 200
    pv = client.get(f"/api/ag/{ag_id}/pv", headers=auth(token_a))
    assert pv.status_code == 200


def test_le_pv_indique_presents_et_representes(db, copro_a, syndic_a, client, token_a):
    import io
    from pypdf import PdfReader
    marie, paul = _immeuble(db, copro_a, syndic_a, [450, 450])
    ag_id = _ag(client, token_a)
    _repondre(client, ag_id, marie, copro_a, reponse="pouvoir", mandataire_id=paul.id)
    _repondre(client, ag_id, paul, copro_a, reponse="present")
    pdf = client.get(f"/api/ag/{ag_id}/pv", headers=auth(token_a)).content
    texte = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "1 copropriétaire(s) présent(s) et 1 représenté(s)" in " ".join(texte.split())
    assert "représenté(e) par Membre c2@exemple.fr" in " ".join(texte.split())


def test_compte_supprime(client, db, copro_a, syndic_a, token_a):
    marie, paul = _immeuble(db, copro_a, syndic_a, [450, 450])
    ag_id = _ag(client, token_a)
    _repondre(client, ag_id, marie, copro_a, reponse="pouvoir", mandataire_id=paul.id)
    db.query(Lot).filter(Lot.proprietaire_id == paul.id).update({Lot.proprietaire_id: None})
    db.commit()
    assert client.delete(f"/api/auth/users/{paul.id}", headers=auth(token_a)).status_code == 200
    db.expire_all()
    r = db.query(AgReponse).one()
    assert (r.reponse, r.mandataire_id) == ("incertain", None)


def test_migration(tmp_path):
    from alembic import command
    from sqlalchemy import create_engine, inspect
    from app import demarrage
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = demarrage.config_alembic(url)
    command.upgrade(cfg, "head")
    assert "ag_reponses" in inspect(create_engine(url)).get_table_names()
    command.downgrade(cfg, "e1f2a3b4c5d6")
    assert "ag_reponses" not in inspect(create_engine(url)).get_table_names()
    command.upgrade(cfg, "head")
