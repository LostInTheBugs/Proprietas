"""Google Drive comme drive de la copropriété (phase 2 du projet Drive, demande de Fred du 16/11/2026).

Choix de Fred (17/11/2026) : construire d'abord sur un faux Google, essai réel ensuite (instance de test
sur vm-test) ; Google Drive avant OneDrive.

Règles :
- application Google : celle de la copropriété (Réglages → Drive, depuis la 2026.11.040,
  tests/test_drive_google_application.py), sinon celle de l'instance (COPRO_GOOGLE_CLIENT_ID / _SECRET) ;
- le syndic choisit le dossier, puis « Se connecter à Google Drive » : page de Google (portée drive.file,
  accès hors connexion), retour sur /api/drive/google/retour avec un état signé (15 min) ;
- au retour : échange du code, essai d'écriture, compte Google relevé ; le drive n'est branché que si
  tout réussit ; sinon retour dans Réglages avec la raison ;
- le jeton de renouvellement est chiffré en base (colonne du mot de passe du drive), jamais renvoyé ;
- ensuite, tout marche comme avec WebDAV : nouveaux fichiers rangés dans le dossier de leur catégorie,
  déplacement, vérification, fichier renommé retrouvé, sauvegarde sur le drive ;
- une suppression met le fichier à la corbeille de Google Drive (récupérable) ;
- autorisation retirée chez Google : message clair « reconnectez Google Drive » ;
- débrancher retire l'autorisation chez Google ; même règles qu'en WebDAV (pas avec des documents dessus) ;
- deux copropriétés de l'instance ne partagent pas un dossier du même compte Google.
"""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from sqlalchemy import text

from app.core import drive, drive_google
from app.core.config import get_settings
from app.core.security import create_access_token
from app.core.stockage import StockageIndisponible
from app.models.audit import AuditLog
from app.models.copropriete import Copropriete
from app.models.document import Document
from tests.conftest import _make_membre, auth
from tests.faux_google import CODE, DOSSIER as MIME_DOSSIER, FauxGoogle
from tests.test_drive import _deposer

DOSSIER = "Proprietas/Résidence A"


@pytest.fixture()
def google(monkeypatch):
    g = FauxGoogle()
    monkeypatch.setattr(drive, "TRANSPORT", g.transport())
    s = get_settings()
    monkeypatch.setattr(s, "google_client_id", "appli.apps.googleusercontent.com")
    monkeypatch.setattr(s, "google_client_secret", "secret-appli")
    monkeypatch.setattr(s, "frontend_url", "https://copro.exemple.fr")
    drive_google._jetons.clear()
    return g


def _connecter(client, token, dossier=DOSSIER):
    r = client.post("/api/drive/google/connecter", json={"dossier": dossier}, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["adresse"]


def _retour(client, adresse, code=CODE, **autres):
    etat = parse_qs(urlsplit(adresse).query)["state"][0]
    r = client.get("/api/drive/google/retour", params={"state": etat, "code": code, **autres}, follow_redirects=False)
    assert r.status_code == 303, r.text
    cible = urlsplit(r.headers["location"])
    assert cible.path == "/settings"
    return {k: v[0] for k, v in parse_qs(cible.query).items()}


def _brancher(client, token, google, dossier=DOSSIER):
    res = _retour(client, _connecter(client, token, dossier))
    assert "drive_ok" in res, res
    return res


# ---------------------------------------------------------------- disponibilité, connexion
def test_sans_application_il_faut_ses_codes(client, db, copro_a, syndic_a, token_a):
    assert client.get("/api/drive", headers=auth(token_a)).json()["google"]["source"] == ""
    r = client.post("/api/drive/google/connecter", json={"dossier": DOSSIER}, headers=auth(token_a))
    assert r.status_code == 422 and "identifiant client et le code secret" in r.json()["detail"]


def test_adresse_de_connexion(client, db, copro_a, syndic_a, token_a, google):
    assert client.get("/api/drive", headers=auth(token_a)).json()["google"]["source"] == "instance"
    adresse = _connecter(client, token_a)
    u = urlsplit(adresse)
    p = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert f"{u.scheme}://{u.netloc}{u.path}" == "https://accounts.google.com/o/oauth2/v2/auth"
    assert p["client_id"] == "appli.apps.googleusercontent.com" and p["response_type"] == "code"
    assert p["redirect_uri"] == "https://copro.exemple.fr/api/drive/google/retour"
    assert p["scope"] == "https://www.googleapis.com/auth/drive.file"
    assert (p["access_type"], p["prompt"]) == ("offline", "consent")
    assert "secret-appli" not in adresse
    # L'état ne vaut pas jeton d'accès.
    assert client.get("/api/drive", headers=auth(p["state"])).status_code == 401
    assert client.post("/api/drive/google/connecter", json={"dossier": "../x"}, headers=auth(token_a)).status_code == 422


def test_brancher_google_drive(client, db, copro_a, syndic_a, token_a, google):
    res = _brancher(client, token_a, google)
    assert "syndic@exemple.fr" in res["drive_ok"]
    etat = client.get("/api/drive", headers=auth(token_a)).json()
    assert (etat["type"], etat["utilisateur"], etat["dossier"], etat["url"]) == ("google", "syndic@exemple.fr", DOSSIER, "")
    assert "rt-" not in json.dumps(etat)
    # Jeton de renouvellement chiffré en base.
    brut = db.execute(text("SELECT drive_password FROM coproprietes WHERE id = :i"), {"i": copro_a.id}).scalar()
    assert brut.startswith("enc:v1:") and "rt-" not in brut
    # L'essai a créé le dossier, et n'a rien laissé (le fichier témoin est supprimé, pas mis à la corbeille).
    dossiers = {google.chemin(i) for i, f in google.fichiers.items() if f["mimeType"] == MIME_DOSSIER}
    assert dossiers == {"Proprietas", DOSSIER} and google.chemins() == [] and google.corbeille() == []
    assert db.query(AuditLog).filter(AuditLog.action == "drive_branche").one().detail.startswith("Google Drive syndic@")


def test_retours_refuses(client, db, copro_a, syndic_a, token_a, google):
    adresse = _connecter(client, token_a)
    assert "annulée" in _retour(client, adresse, code="", error="access_denied")["drive_erreur"]
    assert "Google Drive non branché" in _retour(client, adresse, code="mauvais")["drive_erreur"]
    google.portee_refusee = True
    assert "accès aux fichiers" in _retour(client, adresse)["drive_erreur"]
    google.portee_refusee = False
    # État falsifié ou expiré.
    s = get_settings()
    for etat in ("n'importe quoi",
                 jwt.encode({"scope": "drive_google", "sub": str(syndic_a.id), "copro": copro_a.id, "dossier": DOSSIER,
                             "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}, s.secret_key, algorithm=s.algorithm),
                 jwt.encode({"scope": "drive_google", "sub": str(syndic_a.id), "copro": copro_a.id, "dossier": DOSSIER,
                             "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}, "autre-cle", algorithm=s.algorithm),
                 create_access_token(syndic_a.id, copro_a.id)):
        r = client.get("/api/drive/google/retour", params={"state": etat, "code": CODE}, follow_redirects=False)
        assert "expiré ou invalide" in r.headers["location"] or "invalide" in r.headers["location"]
    assert client.get("/api/drive", headers=auth(token_a)).json()["type"] == ""


def test_retour_d_un_compte_qui_n_est_plus_syndic(client, db, copro_a, syndic_a, token_a, google):
    adresse = _connecter(client, token_a)
    syndic_a.role = "membre"
    db.commit()
    assert "refusée" in _retour(client, adresse)["drive_erreur"]


def test_reserve_au_syndic(client, db, copro_a, syndic_a, google):
    membre = create_access_token(_make_membre(db, "m@test.fr", copro_a).id, copro_a.id)
    assert client.post("/api/drive/google/connecter", json={"dossier": DOSSIER}, headers=auth(membre)).status_code == 403


# ---------------------------------------------------------------- fichiers
def test_fichiers_ranges_sur_google_drive(client, db, copro_a, syndic_a, token_a, google, tmp_path, monkeypatch):
    from app.routes import documents
    monkeypatch.setattr(documents.settings, "upload_dir", str(tmp_path))
    _brancher(client, token_a, google)
    a = _deposer(client, token_a).json()
    b = _deposer(client, token_a, contenu=b"%PDF-autre").json()
    from datetime import date
    jour = date.today().isoformat()
    assert (a["emplacement"], a["fichier"]) == ("drive", f"Factures/{jour} Facture d'électricité.pdf")
    assert b["fichier"] == f"Factures/{jour} Facture d'électricité (2).pdf"
    assert google.chemins() == sorted([f"{DOSSIER}/{a['fichier']}", f"{DOSSIER}/{b['fichier']}"])
    assert list(tmp_path.iterdir()) == []
    r = client.get(f"/api/documents/{a['id']}/download", headers=auth(token_a))
    assert r.status_code == 200 and r.content == b"%PDF-1 essai" and r.headers["content-length"] == "12"
    # Suppression = corbeille de Google Drive.
    assert client.delete(f"/api/documents/{a['id']}", headers=auth(token_a)).status_code == 200
    assert google.chemins() == [f"{DOSSIER}/{b['fichier']}"] and google.corbeille() == [f"{DOSSIER}/{a['fichier']}"]
    # Un seul jeton d'accès pour toute la série (gardé en mémoire jusqu'à son expiration).
    assert google.jetons_demandes == 2                  # échange du code + 1 renouvellement


def test_apostrophes_dans_les_noms(google, monkeypatch):
    assert drive_google._q("l'été \\ x") == "'l\\'été \\\\ x'"
    g = google
    g.renouvellements.add("rt-x")
    st = drive_google.StockageGoogleDrive("appli.apps.googleusercontent.com", "secret-appli", "rt-x",
                                          "Proprietas/L'Orée du bois")
    import io
    st.enregistrer("Autres/d'abord l'été.pdf", io.BytesIO(b"x"))
    assert st.taille("Autres/d'abord l'été.pdf") == 1 and st.taille("Autres/dabord lete.pdf") is None
    assert st.lister_arbre() == {"Autres/d'abord l'été.pdf": 1}


def test_fichier_renomme_dans_google_drive_retrouve(client, db, copro_a, syndic_a, token_a, google):
    _brancher(client, token_a, google)
    doc = _deposer(client, token_a).json()
    archives = google._creer("Archives", next(i for i, f in google.fichiers.items() if google.chemin(i) == DOSSIER),
                             MIME_DOSSIER)
    google.deplacer(f"{DOSSIER}/{doc['fichier']}", dossier_id=archives, nom="EDF.pdf")
    v = client.get("/api/drive/verification", headers=auth(token_a)).json()
    assert [i["id"] for i in v["introuvables"]] == [doc["id"]] and v["non_rattaches"] == [{"chemin": "Archives/EDF.pdf", "taille": 12}]
    r = client.post("/api/drive/retrouver", headers=auth(token_a)).json()
    assert r["relies"][0]["nouveau"] == "Archives/EDF.pdf" and r["introuvables"] == []
    assert client.get(f"/api/documents/{doc['id']}/download", headers=auth(token_a)).content == b"%PDF-1 essai"


def test_deplacer_et_sauvegarder_sur_google_drive(client, db, copro_a, syndic_a, token_a, google, tmp_path, monkeypatch):
    from app.routes import documents
    monkeypatch.setattr(documents.settings, "upload_dir", str(tmp_path))
    ancien = _deposer(client, token_a, libelle="Ancien", contenu=b"%PDF-ancien").json()
    _brancher(client, token_a, google)
    assert client.post("/api/drive/deplacer", headers=auth(token_a)).json()["deplaces"] == 1
    assert db.get(Document, ancien["id"]).emplacement == "drive"
    client.put("/api/drive/sauvegarde", json={"auto": True, "mot_de_passe": "sauvegarde-2026"}, headers=auth(token_a))
    r = client.post("/api/drive/sauvegarde/maintenant", headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert [c for c in google.chemins() if "/Sauvegardes/" in c] == [f"{DOSSIER}/{r.json()['fichier']}"]
    assert len(client.get("/api/drive/sauvegardes", headers=auth(token_a)).json()) == 1
    from app.services.drive_sauvegarde import run_sauvegardes_drive
    assert run_sauvegardes_drive(db, datetime.now() + timedelta(days=8)) == {"sauvegardes": 1, "echecs": 0}


# ---------------------------------------------------------------- pannes
def test_autorisation_retiree_chez_google(client, db, copro_a, syndic_a, token_a, google):
    _brancher(client, token_a, google)
    doc = _deposer(client, token_a).json()
    google.renouvellements.clear()                      # le syndic a retiré l'accès dans son compte Google
    drive_google._jetons.clear()
    r = client.get(f"/api/documents/{doc['id']}/download", headers=auth(token_a))
    assert r.status_code == 503 and "reconnectez Google Drive" in r.json()["detail"]
    r = client.post("/api/drive/test", json={"type": "google"}, headers=auth(token_a))
    assert r.json()["ok"] is False and "reconnectez" in r.json()["detail"]
    # Reconnexion sur le même dossier : permise malgré le document, et le fichier redevient lisible.
    _brancher(client, token_a, google)
    assert client.get(f"/api/documents/{doc['id']}/download", headers=auth(token_a)).content == b"%PDF-1 essai"


def test_google_injoignable_et_drive_plein(client, db, copro_a, syndic_a, token_a, google, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "drive_attente_mo", 0)      # dépôts en attente désactivés
    _brancher(client, token_a, google)
    google.panne = True
    drive_google._jetons.clear()
    r = _deposer(client, token_a)
    assert r.status_code == 503 and "injoignable" in r.json()["detail"]
    google.panne, google.plein = False, True
    r = _deposer(client, token_a)
    assert r.status_code == 503 and "plein" in r.json()["detail"]
    assert db.query(Document).count() == 0


def test_application_retiree_de_l_instance(client, db, copro_a, syndic_a, token_a, google, monkeypatch):
    _brancher(client, token_a, google)
    doc = _deposer(client, token_a).json()
    monkeypatch.setattr(get_settings(), "google_client_secret", "")
    r = client.get(f"/api/documents/{doc['id']}/download", headers=auth(token_a))
    assert r.status_code == 503 and "Réglages → Drive de la copropriété" in r.json()["detail"]


# ---------------------------------------------------------------- débrancher, changer
def test_debrancher_retire_l_autorisation(client, db, copro_a, syndic_a, token_a, google):
    _brancher(client, token_a, google)
    db.expire_all()
    jeton = db.get(Copropriete, copro_a.id).drive_password
    doc = _deposer(client, token_a).json()
    assert client.put("/api/drive", json={"type": ""}, headers=auth(token_a)).status_code == 409
    client.delete(f"/api/documents/{doc['id']}", headers=auth(token_a))
    r = client.put("/api/drive", json={"type": ""}, headers=auth(token_a))
    assert r.status_code == 200 and r.json()["type"] == ""
    assert google.revoques == [jeton]


def test_pas_de_changement_de_drive_avec_des_documents(client, db, copro_a, syndic_a, token_a, google):
    _brancher(client, token_a, google)
    _deposer(client, token_a)
    r = client.post("/api/drive/google/connecter", json={"dossier": "Autre"}, headers=auth(token_a))
    assert r.status_code == 409
    from tests.test_drive import _reglages
    r = client.put("/api/drive", json=_reglages(), headers=auth(token_a))      # passer à WebDAV
    assert r.status_code == 409 and "Google Drive" in r.json()["detail"]
    assert client.put("/api/drive", json={"type": "google", "dossier": DOSSIER}, headers=auth(token_a)).status_code == 422


def test_reconnexion_du_meme_compte_garde_l_autorisation(client, db, copro_a, syndic_a, token_a, google):
    """Révoquer l'ancien jeton retirerait chez Google l'autorisation entière du compte, nouveau jeton compris."""
    _brancher(client, token_a, google)
    db.expire_all()
    ancien = db.get(Copropriete, copro_a.id).drive_password
    _brancher(client, token_a, google)
    db.expire_all()
    assert db.get(Copropriete, copro_a.id).drive_password != ancien and google.revoques == []
    r = _deposer(client, token_a)
    assert r.status_code == 200 and r.json()["emplacement"] == "drive", r.text
    assert client.post("/api/drive/test", json={"type": "google"}, headers=auth(token_a)).json()["ok"] is True


def test_reconnexion_avec_un_autre_compte_rend_l_ancien(client, db, copro_a, syndic_a, token_a, google):
    _brancher(client, token_a, google)
    db.expire_all()
    ancien = db.get(Copropriete, copro_a.id).drive_password
    google.compte = "autre@exemple.fr"
    _brancher(client, token_a, google)
    assert google.revoques == [ancien]
    assert client.post("/api/drive/test", json={"type": "google"}, headers=auth(token_a)).json()["ok"] is True


def test_debrancher_garde_le_compte_d_une_autre_copropriete(client, db, copro_a, copro_b, syndic_a, syndic_b,
                                                             token_a, token_b, google):
    """Même compte Google pour deux copropriétés (dossiers différents) : débrancher l'une ne coupe pas l'autre."""
    _brancher(client, token_a, google)
    _brancher(client, token_b, google, dossier="Proprietas/Autre résidence")
    assert client.put("/api/drive", json={"type": ""}, headers=auth(token_b)).status_code == 200
    assert google.revoques == []
    assert client.post("/api/drive/test", json={"type": "google"}, headers=auth(token_a)).json()["ok"] is True


def test_dossier_partage_refuse(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b, google):
    _brancher(client, token_a, google)
    res = _retour(client, _connecter(client, token_b, "Proprietas"))
    assert "autre copropriété" in res["drive_erreur"]
    assert google.revoques == []                        # le compte sert à A : le rendre couperait A
    assert client.post("/api/drive/test", json={"type": "google"}, headers=auth(token_a)).json()["ok"] is True
    # Même dossier, mais un autre compte Google : permis.
    google.compte = "autre@exemple.fr"
    assert "drive_ok" in _retour(client, _connecter(client, token_b, DOSSIER))


def test_sauvegarde_exportee_sans_secret_google(client, db, copro_a, syndic_a, token_a, google):
    from tests.test_sauvegarde import COMPLETE, _export, _ouvrir
    _brancher(client, token_a, google)
    _deposer(client, token_a)
    donnees = json.loads(_ouvrir(_export(client, token_a, COMPLETE)).read("donnees.json"))
    assert "rt-" not in json.dumps(donnees) and "syndic@exemple.fr" not in json.dumps(donnees["coproprietes"])


def test_adresse_de_retour_selon_le_nom_utilise(client, db, copro_a, syndic_a, token_a, google):
    """Instance servie sous deux noms derrière un proxy TLS (cas de la démo et de la production sur le
    même serveur) : le retour se fait sur le nom par lequel le syndic est venu, pas sur COPRO_FRONTEND_URL."""
    def retour(entetes):
        r = client.post("/api/drive/google/connecter", json={"dossier": DOSSIER}, headers={**auth(token_a), **entetes})
        return parse_qs(urlsplit(r.json()["adresse"]).query)["redirect_uri"][0]
    assert retour({"X-Forwarded-Proto": "https", "Host": "demo.exemple.fr"}) == \
        "https://demo.exemple.fr/api/drive/google/retour"
    assert retour({"X-Forwarded-Proto": "https", "X-Forwarded-Host": "copro.exemple.fr"}) == \
        "https://copro.exemple.fr/api/drive/google/retour"
    # Sans https (accès direct, réseau local) : l'adresse publique réglée.
    assert retour({}) == "https://copro.exemple.fr/api/drive/google/retour"
