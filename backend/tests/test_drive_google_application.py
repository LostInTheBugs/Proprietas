"""Application Google saisie dans Proprietas, par copropriété (demande de Fred, 19/11/2026).

Fred avait saisi l'identifiant et le code secret Google dans le formulaire WebDAV (erreur 405) : ils ne
s'entraient que dans le .env du serveur. Désormais :
- Réglages → Drive de la copropriété : on choisit le type de drive, et les champs suivent ; pour Google Drive,
  identifiant client et code secret de l'application Google, et l'adresse de retour à déclarer chez Google ;
- l'application de la copropriété passe avant celle de l'instance (.env), qui reste possible pour toutes ;
- le code secret est chiffré en base, ne ressort jamais, n'est pas dans les sauvegardes ;
- changer d'application quand des fichiers sont sur Google Drive est refusé (l'autre application ne les
  verrait pas, portée drive.file) ;
- des codes Google saisis dans le formulaire WebDAV : message clair au lieu d'une erreur du drive.
"""
from urllib.parse import parse_qs, urlsplit

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app import demarrage
from app.core import drive, drive_google
from app.core.config import get_settings
from app.models.audit import AuditLog
from app.services import sauvegarde
from tests.conftest import auth
from tests.faux_google import FauxGoogle
from tests.test_drive import _deposer
from tests.test_drive_google import DOSSIER, _retour

CID = "108360811579-abtd381q1t2idvt.apps.googleusercontent.com"
SECRET = "GOCSPX-copro-essai"


@pytest.fixture()
def google_seul(monkeypatch):
    """Faux Google, sans application déclarée dans le .env de l'instance."""
    g = FauxGoogle()
    g.applications[CID] = SECRET
    monkeypatch.setattr(drive, "TRANSPORT", g.transport())
    s = get_settings()
    monkeypatch.setattr(s, "google_client_id", "")
    monkeypatch.setattr(s, "google_client_secret", "")
    monkeypatch.setattr(s, "frontend_url", "https://copro.exemple.fr")
    drive_google._jetons.clear()
    return g


def _connecter(client, token, **champs):
    return client.post("/api/drive/google/connecter", json={"dossier": DOSSIER, **champs}, headers=auth(token))


def test_etat_sans_application(client, db, copro_a, syndic_a, token_a, google_seul):
    g = client.get("/api/drive", headers=auth(token_a)).json()["google"]
    assert g == {"source": "", "instance": False, "client_id": "", "secret_defini": False,
                 "retour": "https://copro.exemple.fr/api/drive/google/retour"}
    r = _connecter(client, token_a)
    assert r.status_code == 422 and "identifiant client et le code secret" in r.json()["detail"]


def test_application_de_la_copropriete(client, db, copro_a, syndic_a, token_a, google_seul):
    r = _connecter(client, token_a, client_id=CID, client_secret=SECRET)
    assert r.status_code == 200, r.text
    adresse = r.json()["adresse"]
    assert parse_qs(urlsplit(adresse).query)["client_id"] == [CID] and SECRET not in adresse
    db.refresh(copro_a)
    assert copro_a.google_client_id == CID and copro_a.google_client_secret == SECRET
    brut = db.execute(text("select google_client_secret from coproprietes where id = :i"), {"i": copro_a.id}).scalar()
    assert brut and SECRET not in brut                                   # chiffré en base
    res = _retour(client, adresse)
    assert "drive_ok" in res, res
    assert set(google_seul.clients) == {CID}                             # échange du code avec cette application
    etat = client.get("/api/drive", headers=auth(token_a))
    assert SECRET not in etat.text
    assert etat.json()["google"] == {"source": "copropriete", "instance": False, "client_id": CID,
                                     "secret_defini": True, "retour": "https://copro.exemple.fr/api/drive/google/retour"}
    doc = _deposer(client, token_a).json()
    assert google_seul.chemins() == [f"{DOSSIER}/{doc['fichier']}"]
    db.expire_all()
    assert db.query(AuditLog).filter(AuditLog.action == "drive_google_application").count() == 1


def test_codes_invalides(client, db, copro_a, syndic_a, token_a, google_seul):
    r = _connecter(client, token_a, client_id="abtd381q1t2idvt", client_secret=SECRET)
    assert r.status_code == 422 and "apps.googleusercontent.com" in r.json()["detail"]
    r = _connecter(client, token_a, client_secret=SECRET)
    assert r.status_code == 422 and "identifiant client" in r.json()["detail"]
    r = _connecter(client, token_a, client_id=CID)                      # pas de code secret enregistré
    assert r.status_code == 422
    db.refresh(copro_a)
    assert copro_a.google_client_id == "" and not copro_a.google_client_secret   # rien n'est gardé


def test_la_copropriete_passe_avant_l_instance(client, db, copro_a, syndic_a, token_a, google_seul, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "google_client_id", "appli.apps.googleusercontent.com")
    monkeypatch.setattr(s, "google_client_secret", "secret-appli")
    assert client.get("/api/drive", headers=auth(token_a)).json()["google"]["source"] == "instance"
    adresse = _connecter(client, token_a, client_id=CID, client_secret=SECRET).json()["adresse"]
    assert parse_qs(urlsplit(adresse).query)["client_id"] == [CID]
    assert client.get("/api/drive", headers=auth(token_a)).json()["google"]["source"] == "copropriete"


def test_changer_d_application_avec_des_fichiers_dessus(client, db, copro_a, syndic_a, token_a, google_seul):
    _retour(client, _connecter(client, token_a, client_id=CID, client_secret=SECRET).json()["adresse"])
    assert _deposer(client, token_a).status_code in (200, 201)
    autre = "999999999999-autreappli.apps.googleusercontent.com"
    r = _connecter(client, token_a, client_id=autre, client_secret="GOCSPX-autre")
    assert r.status_code == 409 and "rapatriez-les d'abord" in r.json()["detail"]
    db.refresh(copro_a)
    assert copro_a.google_client_id == CID and copro_a.google_client_secret == SECRET
    # Même application, code secret renouvelé chez Google : permis (code secret vide = le garder).
    google_seul.applications[CID] = "GOCSPX-renouvele"
    assert _connecter(client, token_a, client_id=CID, client_secret="GOCSPX-renouvele").status_code == 200
    assert _connecter(client, token_a, client_id=CID).status_code == 200
    db.refresh(copro_a)
    assert copro_a.google_client_secret == "GOCSPX-renouvele"


@pytest.mark.parametrize("champs", [
    {"url": "https://copro-9republique.cloudfr.net/api/drive/google/retour", "utilisateur": "x"},
    {"url": "https://cloud.exemple.fr/remote.php/dav/files/syndic/", "utilisateur": CID},
])
def test_codes_google_dans_le_formulaire_webdav(client, db, copro_a, syndic_a, token_a, champs):
    corps = {"type": "webdav", "mot_de_passe": SECRET, "dossier": DOSSIER, **champs}
    for methode, chemin in (("post", "/api/drive/test"), ("put", "/api/drive")):
        r = getattr(client, methode)(chemin, json=corps, headers=auth(token_a))
        assert r.status_code == 422, r.text
        assert "choisissez « Google Drive »" in r.json()["detail"]


def test_pas_dans_les_sauvegardes():
    assert {"google_client_id", "google_client_secret"} <= sauvegarde.EXCLUES["coproprietes"]


def test_migration(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = demarrage.config_alembic(url)
    command.upgrade(cfg, "c9d0e1f2a3b4")
    with create_engine(url).begin() as c:
        c.execute(text("insert into coproprietes (id, nom) values (1, 'R')"))
    command.upgrade(cfg, "head")
    with create_engine(url).connect() as c:
        assert c.execute(text("select google_client_id, google_client_secret from coproprietes")).one() == ("", None)
    command.downgrade(cfg, "c9d0e1f2a3b4")
    assert "google_client_id" not in [x["name"] for x in inspect(create_engine(url)).get_columns("coproprietes")]
    command.upgrade(cfg, "head")
