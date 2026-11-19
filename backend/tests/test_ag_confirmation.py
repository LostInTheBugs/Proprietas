"""E-mail d'information sur l'AG : lien personnel « J'ai bien reçu ce message » (demande de Fred, 19/11/2026).

- un lien par destinataire (jeton aléatoire), seulement si l'adresse publique de l'application est connue ;
- le lien ouvre une page avec un bouton : seul le POST confirme (un antivirus qui ouvre le lien ne confirme rien) ;
- la date de confirmation s'affiche dans la liste des envois ; une deuxième confirmation ne la change pas ;
- pas d'image de suivi (CNIL : consentement nécessaire, et peu fiable) ;
- la mention « convocation officielle » tient en une ligne, en bas du message.
"""
from datetime import date, timedelta

import pytest

from app.core.config import get_settings
from app.models.invitation import Invitation
from app.models.lot import Lot
from app.routes import ag as routes_ag
from tests.conftest import _make_membre, auth


@pytest.fixture()
def envois(monkeypatch):
    boite = []
    monkeypatch.setattr(routes_ag, "envoyer_email", lambda copro, dest, sujet, corps: boite.append((dest, corps)))
    return boite


def _ag_avec_proprietaires(client, db, copro, token):
    for i, email in enumerate(("marie@exemple.fr", "paul@exemple.fr"), start=1):
        u = _make_membre(db, email, copro)
        db.add(Lot(copropriete_id=copro.id, numero=str(i), tantiemes=500, proprietaire_id=u.id))
    db.commit()
    r = client.post("/api/ag", json={"date": str(date.today() + timedelta(days=40))}, headers=auth(token))
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_lien_personnel_et_confirmation(client, db, copro_a, syndic_a, token_a, envois, monkeypatch):
    monkeypatch.setattr(get_settings(), "frontend_url", "https://copro.exemple.fr/")
    ag_id = _ag_avec_proprietaires(client, db, copro_a, token_a)
    r = client.post(f"/api/ag/{ag_id}/invitations", headers=auth(token_a))
    assert r.json()["envoyes"] == 2
    liens = {}
    for dest, corps in envois:
        ligne = next(l for l in corps.splitlines() if "/api/ag/confirmation/" in l)
        assert ligne.startswith("https://copro.exemple.fr/api/ag/confirmation/")
        assert corps.rstrip().splitlines()[-1].startswith("Pour information : la convocation officielle")
        assert "<img" not in corps
        liens[dest] = ligne.removeprefix("https://copro.exemple.fr")
    assert len(set(liens.values())) == 2                       # un lien par destinataire
    lien = liens["marie@exemple.fr"]
    # Ouvrir le lien (GET) ne confirme rien : il faut envoyer le formulaire (depuis la 2026.11.042, la page demande
    # aussi la réponse : présent, pouvoir, absent, ne sait pas ; tests/test_ag_presences.py).
    page = client.get(lien)
    assert page.status_code == 200 and "Envoyer ma réponse" in page.text and 'method="post"' in page.text
    assert db.query(Invitation).filter(Invitation.confirme_le.isnot(None)).count() == 0
    merci = client.post(lien)                                  # formulaire des liens d'avant : réception seule
    assert merci.status_code == 200 and "confirmée" in merci.text
    invs = {i["personne_email"]: i for i in client.get(f"/api/ag/{ag_id}/invitations", headers=auth(token_a)).json()}
    assert invs["marie@exemple.fr"]["confirme_le"] and invs["paul@exemple.fr"]["confirme_le"] is None
    premiere = invs["marie@exemple.fr"]["confirme_le"]
    client.post(lien)
    invs = {i["personne_email"]: i for i in client.get(f"/api/ag/{ag_id}/invitations", headers=auth(token_a)).json()}
    assert invs["marie@exemple.fr"]["confirme_le"] == premiere


def test_sans_adresse_publique_pas_de_lien(client, db, copro_a, syndic_a, token_a, envois, monkeypatch):
    monkeypatch.setattr(get_settings(), "frontend_url", "")
    ag_id = _ag_avec_proprietaires(client, db, copro_a, token_a)
    client.post(f"/api/ag/{ag_id}/invitations", headers=auth(token_a))
    assert envois and all("/api/ag/confirmation/" not in corps for _, corps in envois)
    assert db.query(Invitation).filter(Invitation.jeton.isnot(None)).count() == 0


def test_lien_inconnu(client):
    for methode in (client.get, client.post):
        r = methode("/api/ag/confirmation/inconnu-inconnu-inconnu-0000")
        assert r.status_code == 200 and "Lien inconnu" in r.text
    assert "Lien inconnu" in client.post("/api/ag/confirmation/court").text
