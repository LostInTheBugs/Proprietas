"""Drive de la copropriété (demande de Fred, 16/11/2026) : ranger les fichiers sur un drive —
ownCloud, Nextcloud, Synology d'abord (WebDAV) — dans une arborescence lisible
« Proprietas / NOM DE LA COPRO / Factures, Contrats… ». Première livraison : brancher le drive et y
écrire les nouveaux fichiers.

Choix de Fred : le drive est le stockage PRINCIPAL (rien n'est gardé sur le serveur).

Règles :
- Réglages (syndic) : adresse WebDAV, identifiant, mot de passe, dossier (proposé : « Proprietas/<nom de
  la copropriété> »). On n'enregistre que si l'essai réussit : dossier créé, fichier témoin écrit, relu,
  supprimé. Le mot de passe est chiffré en base et ne ressort jamais ; vide = on garde l'ancien.
- Drive branché : chaque nouveau fichier part sur le drive, dans le dossier de sa catégorie, sous le nom
  « AAAA-MM-JJ libellé.ext » ; si le nom est pris : « … (2).ext ». Rien n'est écrit sur le serveur.
- Les documents déjà déposés restent où ils sont et restent lisibles.
- Téléchargement et suppression vont chercher le fichier là où il est. Fichier renommé ou supprimé sur
  le drive : 404 explicite. Drive injoignable, mot de passe refusé, quota : 503 explicite, et la fiche
  n'est pas supprimée.
- Tant que des documents sont sur le drive : ni débranchement, ni changement de dossier (409).
- Adresse : http(s) seulement ; refus de la machine elle-même, des adresses de lien local et réservées ;
  réseau local admis sauf COPRO_DRIVE_RESEAU_LOCAL=false ; aucune redirection suivie.
- Sauvegarde : avec les fichiers, ceux du drive entrent dans l'archive ; les réglages du drive ne sont
  jamais exportés ; à l'import, les fichiers vont dans le stockage de l'instance.
- COPRO_DRIVE_ACTIF=false retire la fonction de l'instance.
"""
import io
import json
import socket
from datetime import date

import pytest
from sqlalchemy import text

from app.core import drive
from app.core.config import get_settings
from app.core.security import create_access_token
from app.core.stockage import NomInvalide, StockageIndisponible
from app.models.audit import AuditLog
from app.models.copropriete import Copropriete
from app.models.document import Document
from tests.conftest import _make_membre, auth
from tests.faux_webdav import URL, FauxWebDAV

MDP = "secret-drive"
DOSSIER = "Proprietas/Résidence A"
AUJ = date.today().isoformat()


@pytest.fixture()
def serveur(monkeypatch):
    s = FauxWebDAV()
    monkeypatch.setattr(drive, "TRANSPORT", s.transport())
    # Résolution de nom figée : cloud.exemple.fr → une adresse publique.
    monkeypatch.setattr(socket, "getaddrinfo", lambda hote, port, **k: [(2, 1, 6, "", (ADRESSES.get(hote, "93.184.216.34"), port))])
    return s


ADRESSES = {"localhost": "127.0.0.1", "nas.maison": "192.168.1.50", "metadonnees": "169.254.169.254"}


def _reglages(**champs):
    return {"type": "webdav", "url": URL + "/", "utilisateur": "syndic", "mot_de_passe": MDP, "dossier": DOSSIER,
            **champs}


def _brancher(client, token, **champs):
    r = client.put("/api/drive", json=_reglages(**champs), headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _deposer(client, token, libelle="Facture d'électricité", categorie="facture", nom="scan.pdf", contenu=b"%PDF-1 essai"):
    return client.post("/api/documents", data={"categorie": categorie, "libelle": libelle},
                       files={"fichier": (nom, contenu, "application/pdf")}, headers=auth(token))


# ---------------------------------------------------------------- noms
def test_noms_lisibles_et_surs():
    assert drive.dossier_propose("Résidence : Les Tilleuls / A") == "Proprietas/Résidence Les Tilleuls A"
    assert drive.nom_lisible(date(2026, 11, 16), "Facture d'électricité <EDF> ?", ".pdf") == \
        "2026-11-16 Facture d'électricité EDF.pdf"
    assert drive.nom_lisible(date(2026, 1, 2), " .. ", ".pdf") == "2026-01-02 document.pdf"
    assert drive.valider_chemin("Factures/2026 a.pdf") == ["Factures", "2026 a.pdf"]
    for mauvais in ("", "/etc/passwd", "../x", "a/../b", "a//b", "a\\b", "a/./b"):
        with pytest.raises(NomInvalide):
            drive.valider_chemin(mauvais)


# ---------------------------------------------------------------- réglages
def test_brancher_le_drive(client, db, copro_a, syndic_a, token_a, serveur):
    avant = client.get("/api/drive", headers=auth(token_a)).json()
    assert avant["google"] == {"source": "", "instance": False, "client_id": "", "secret_defini": False,
                               "retour": avant["google"]["retour"]}
    assert avant["google"]["retour"].endswith("/api/drive/google/retour")
    del avant["google"]
    assert avant == {"autorise": True, "type": "", "url": "", "utilisateur": "", "dossier": "",
                     "mot_de_passe_defini": False, "documents_sur_le_drive": 0,
                     "documents_sur_le_serveur": 0,
                     "dossier_propose": drive.dossier_propose(copro_a.nom),
                     "en_attente": {"nombre": 0, "octets": 0, "plafond_mo": 50},
                     "sauvegarde": {"auto": False, "mot_de_passe_defini": False, "derniere": None, "prochaine": None,
                                    "erreur": "", "gardees": 8}}
    etat = _brancher(client, token_a)
    assert (etat["type"], etat["url"], etat["utilisateur"], etat["dossier"], etat["mot_de_passe_defini"]) == \
        ("webdav", URL, "syndic", DOSSIER, True)
    assert MDP not in json.dumps(etat)
    # L'essai a créé le dossier et n'a rien laissé derrière lui.
    assert {"Proprietas", DOSSIER} <= serveur.dossiers and serveur.chemins() == []
    # Chiffré en base, relu en clair par le code.
    brut = db.execute(text("SELECT drive_password FROM coproprietes WHERE id = :i"), {"i": copro_a.id}).scalar()
    assert brut.startswith("enc:v1:") and MDP not in brut
    db.expire_all()
    assert db.get(Copropriete, copro_a.id).drive_password == MDP
    assert db.query(AuditLog).filter(AuditLog.action == "drive_branche").count() == 1


def test_reglages_refuses_si_l_essai_echoue(client, db, copro_a, syndic_a, token_a, serveur):
    r = client.put("/api/drive", json=_reglages(mot_de_passe="faux"), headers=auth(token_a))
    assert r.status_code == 422 and "identifiant ou le mot de passe" in r.json()["detail"]
    serveur.panne = True
    r = client.put("/api/drive", json=_reglages(), headers=auth(token_a))
    assert r.status_code == 422 and "injoignable" in r.json()["detail"]
    serveur.panne, serveur.redirige = False, True
    r = client.put("/api/drive", json=_reglages(), headers=auth(token_a))
    assert r.status_code == 422 and "adresse finale" in r.json()["detail"]
    db.expire_all()
    assert not db.get(Copropriete, copro_a.id).drive_type            # rien n'a été enregistré


def test_essai_sans_enregistrer(client, db, copro_a, syndic_a, token_a, serveur):
    r = client.post("/api/drive/test", json=_reglages(), headers=auth(token_a))
    assert r.json() == {"ok": True, "detail": f"Connexion réussie : le dossier « {DOSSIER} » est prêt."}
    r = client.post("/api/drive/test", json=_reglages(mot_de_passe="faux"), headers=auth(token_a))
    assert r.json()["ok"] is False
    assert client.get("/api/drive", headers=auth(token_a)).json()["type"] == ""


def test_mot_de_passe_vide_garde_l_ancien(client, db, copro_a, syndic_a, token_a, serveur):
    _brancher(client, token_a)
    etat = _brancher(client, token_a, mot_de_passe="", utilisateur="syndic")
    assert etat["mot_de_passe_defini"] is True
    db.expire_all()
    assert db.get(Copropriete, copro_a.id).drive_password == MDP


@pytest.mark.parametrize("url,message", [
    ("ftp://cloud.exemple.fr/dav", "https://"),
    ("https://syndic:secret@cloud.exemple.fr/dav", "identifiant"),
    ("http://localhost/dav", "lui-même"),
    ("http://metadonnees/latest", "lui-même"),
    ("cloud.exemple.fr/dav", "https://"),
])
def test_adresses_refusees(client, copro_a, syndic_a, token_a, serveur, url, message):
    r = client.put("/api/drive", json=_reglages(url=url), headers=auth(token_a))
    assert r.status_code == 422 and message in r.json()["detail"], r.text
    assert serveur.requetes == []                                    # le serveur n'a rien appelé


def test_reseau_local_admis_sauf_reglage(copro_a, serveur, monkeypatch):
    assert drive.verifier_adresse("http://nas.maison:5005/", True) == "http://nas.maison:5005"
    with pytest.raises(drive.AdresseRefusee, match="réseau local"):
        drive.verifier_adresse("http://nas.maison:5005/", False)


def test_dossier_invalide(client, copro_a, syndic_a, token_a, serveur):
    for dossier in ("", "  ", "../ailleurs", "/"):
        r = client.put("/api/drive", json=_reglages(dossier=dossier), headers=auth(token_a))
        assert r.status_code == 422, (dossier, r.text)
    # Barres en trop et caractères interdits : nettoyés.
    assert _brancher(client, token_a, dossier="/Proprietas//Ma copro: A/")["dossier"] == "Proprietas/Ma copro A"


def test_reserve_au_syndic_et_isole(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b, serveur):
    _brancher(client, token_a)
    assert client.get("/api/drive", headers=auth(token_b)).json()["type"] == ""
    membre = create_access_token(_make_membre(db, "m@test.fr", copro_a).id, copro_a.id)
    assert client.get("/api/drive", headers=auth(membre)).status_code == 403
    assert client.put("/api/drive", json=_reglages(), headers=auth(membre)).status_code == 403
    assert client.post("/api/drive/test", json=_reglages(), headers=auth(membre)).status_code == 403


def test_fonction_retiree_de_l_instance(client, db, copro_a, syndic_a, token_a, serveur, monkeypatch):
    _brancher(client, token_a)
    monkeypatch.setattr(get_settings(), "drive_actif", False)
    assert client.get("/api/drive", headers=auth(token_a)).json()["autorise"] is False
    assert client.put("/api/drive", json=_reglages(), headers=auth(token_a)).status_code == 403
    # Les nouveaux fichiers repartent dans le stockage de l'instance.
    r = _deposer(client, token_a)
    assert r.status_code == 200 and r.json()["emplacement"] == ""
    assert serveur.chemins() == []


# ---------------------------------------------------------------- documents
def test_nouveau_fichier_range_sur_le_drive(client, db, copro_a, syndic_a, token_a, serveur, tmp_path, monkeypatch):
    from app.routes import documents
    monkeypatch.setattr(documents.settings, "upload_dir", str(tmp_path))
    _brancher(client, token_a)
    r = _deposer(client, token_a)
    assert r.status_code == 200, r.text
    attendu = f"Factures/{AUJ} Facture d'électricité.pdf"
    assert (r.json()["emplacement"], r.json()["fichier"]) == ("drive", attendu)
    assert serveur.chemins() == [f"{DOSSIER}/{attendu}"]
    assert serveur.fichiers[f"{DOSSIER}/{attendu}"] == b"%PDF-1 essai"
    assert list(tmp_path.iterdir()) == []                              # rien sur le serveur
    # Longueur annoncée (pas d'envoi par morceaux) et jamais le mot de passe dans l'adresse.
    put = [e for (m, _), e in zip(serveur.requetes, serveur.entetes) if m == "PUT"][-1]
    assert put["content-length"] == "12" and "transfer-encoding" not in put
    # Un dossier par catégorie.
    _deposer(client, token_a, libelle="Contrat ascenseur", categorie="contrat")
    _deposer(client, token_a, libelle="Divers", categorie="inconnue")
    assert f"{DOSSIER}/Contrats/{AUJ} Contrat ascenseur.pdf" in serveur.chemins()
    assert f"{DOSSIER}/Autres/{AUJ} Divers.pdf" in serveur.chemins()
    assert client.get("/api/drive", headers=auth(token_a)).json()["documents_sur_le_drive"] == 3


def test_nom_deja_pris(client, db, copro_a, syndic_a, token_a, serveur):
    _brancher(client, token_a)
    noms = [_deposer(client, token_a, contenu=b"%PDF-" + str(n).encode()).json()["fichier"] for n in range(3)]
    assert noms == [f"Factures/{AUJ} Facture d'électricité.pdf", f"Factures/{AUJ} Facture d'électricité (2).pdf",
                    f"Factures/{AUJ} Facture d'électricité (3).pdf"]
    assert serveur.fichiers[f"{DOSSIER}/{noms[1]}"] == b"%PDF-1"            # aucun fichier écrasé


def test_telecharger_et_supprimer(client, db, copro_a, syndic_a, token_a, serveur):
    _brancher(client, token_a)
    doc = _deposer(client, token_a).json()
    r = client.get(f"/api/documents/{doc['id']}/download", headers=auth(token_a))
    assert r.status_code == 200 and r.content == b"%PDF-1 essai"
    assert r.headers["content-length"] == "12" and r.headers["content-type"] == "application/pdf"
    assert client.delete(f"/api/documents/{doc['id']}", headers=auth(token_a)).status_code == 200
    assert serveur.chemins() == [] and db.query(Document).count() == 0


def test_documents_d_avant_restent_sur_le_serveur(client, db, copro_a, syndic_a, token_a, serveur, tmp_path, monkeypatch):
    from app.routes import documents
    monkeypatch.setattr(documents.settings, "upload_dir", str(tmp_path))
    ancien = _deposer(client, token_a, libelle="Ancien").json()
    assert ancien["emplacement"] == "" and len(list(tmp_path.iterdir())) == 1
    _brancher(client, token_a)
    r = client.get(f"/api/documents/{ancien['id']}/download", headers=auth(token_a))
    assert r.status_code == 200 and r.content == b"%PDF-1 essai"
    assert client.delete(f"/api/documents/{ancien['id']}", headers=auth(token_a)).status_code == 200
    assert list(tmp_path.iterdir()) == []


def test_fichier_renomme_ou_supprime_sur_le_drive(client, db, copro_a, syndic_a, token_a, serveur):
    _brancher(client, token_a)
    doc = _deposer(client, token_a).json()
    serveur.fichiers.clear()                                           # quelqu'un l'a renommé côté drive
    r = client.get(f"/api/documents/{doc['id']}/download", headers=auth(token_a))
    assert r.status_code == 404 and "introuvable sur le drive" in r.json()["detail"]
    # La fiche peut partir : il n'y a plus de fichier à laisser derrière.
    assert client.delete(f"/api/documents/{doc['id']}", headers=auth(token_a)).status_code == 200


def test_drive_injoignable(client, db, copro_a, syndic_a, token_a, serveur, monkeypatch):
    # Dépôts en attente désactivés (COPRO_DRIVE_ATTENTE_MO=0) : le dépôt est refusé (voir test_drive_attente.py).
    monkeypatch.setattr(get_settings(), "drive_attente_mo", 0)
    _brancher(client, token_a)
    doc = _deposer(client, token_a).json()
    serveur.panne = True
    r = client.get(f"/api/documents/{doc['id']}/download", headers=auth(token_a))
    assert r.status_code == 503 and "injoignable" in r.json()["detail"]
    r = _deposer(client, token_a, libelle="Autre")
    assert r.status_code == 503 and "injoignable" in r.json()["detail"]
    assert client.delete(f"/api/documents/{doc['id']}", headers=auth(token_a)).status_code == 503
    assert db.query(Document).count() == 1                             # ni fiche perdue, ni fiche fantôme
    serveur.panne, serveur.plein = False, True
    r = _deposer(client, token_a, libelle="Autre")
    assert r.status_code == 503 and "plein" in r.json()["detail"]


def test_ni_debranchement_ni_changement_de_dossier_avec_des_documents(client, db, copro_a, syndic_a, token_a, serveur):
    _brancher(client, token_a)
    doc = _deposer(client, token_a).json()
    r = client.put("/api/drive", json={"type": ""}, headers=auth(token_a))
    assert r.status_code == 409 and "1 document" in r.json()["detail"]
    r = client.put("/api/drive", json=_reglages(dossier="Autre dossier"), headers=auth(token_a))
    assert r.status_code == 409
    _brancher(client, token_a, utilisateur="syndic")                   # même dossier : permis
    client.delete(f"/api/documents/{doc['id']}", headers=auth(token_a))
    r = client.put("/api/drive", json={"type": ""}, headers=auth(token_a))
    assert r.status_code == 200 and r.json()["type"] == "" and r.json()["mot_de_passe_defini"] is False
    assert db.query(AuditLog).filter(AuditLog.action == "drive_debranche").count() == 1
    assert _deposer(client, token_a).json()["emplacement"] == ""


def test_chemin_forge_en_base(client, db, copro_a, syndic_a, token_a, serveur):
    _brancher(client, token_a)
    doc = Document(copropriete_id=copro_a.id, categorie="autre", libelle="x", fichier="../../autre copro/secret.pdf",
                   emplacement="drive", date_ajout=date.today())
    db.add(doc)
    db.commit()
    avant = len(serveur.requetes)
    assert client.get(f"/api/documents/{doc.id}/download", headers=auth(token_a)).status_code == 404
    assert len(serveur.requetes) == avant                              # aucune requête partie


def test_reponse_xml_piegee(copro_a, serveur, monkeypatch):
    import httpx
    piege = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><d:multistatus xmlns:d="DAV:">&a;</d:multistatus>'
    monkeypatch.setattr(drive, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(207, content=piege)))
    st = drive.StockageWebDAV(URL, "syndic", MDP, DOSSIER)
    with pytest.raises(StockageIndisponible, match="illisible"):
        st.taille("Factures/a.pdf")


# ---------------------------------------------------------------- sauvegarde et espace
def test_sauvegarde_avec_les_fichiers_du_drive(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b,
                                               serveur, tmp_path, monkeypatch):
    from app.routes import documents
    from tests.test_sauvegarde import COMPLETE, _export, _import, _ouvrir
    monkeypatch.setattr(documents.settings, "upload_dir", str(tmp_path))
    _brancher(client, token_a)
    doc = _deposer(client, token_a).json()
    z = _ouvrir(_export(client, token_a, COMPLETE))
    donnees = json.loads(z.read("donnees.json"))
    assert z.read(f"documents/{doc['fichier']}") == b"%PDF-1 essai"
    assert donnees["documents"][0]["emplacement"] == ""
    c = donnees["coproprietes"][0]
    assert not any(k.startswith("drive_") for k in c) and MDP not in json.dumps(donnees)
    # Import : la copie n'a pas de drive, son fichier est dans le stockage de l'instance.
    r = _import(client, token_b, _export(client, token_a, COMPLETE))
    assert r.status_code == 200, r.text
    copie = db.query(Document).filter(Document.copropriete_id == r.json()["copropriete_id"]).one()
    assert copie.emplacement == "" and (tmp_path / copie.fichier).read_bytes() == b"%PDF-1 essai"
    assert not db.get(Copropriete, r.json()["copropriete_id"]).drive_type
    # L'original est intact sur le drive.
    assert serveur.chemins() == [f"{DOSSIER}/{doc['fichier']}"]


def test_sauvegarde_sans_fichiers_n_appelle_pas_le_drive(client, db, copro_a, syndic_a, token_a, serveur):
    from tests.test_sauvegarde import _export, _ouvrir
    _brancher(client, token_a)
    _deposer(client, token_a)
    serveur.panne = True
    z = _ouvrir(_export(client, token_a, {"mot_de_passe": "", "donnees_personnelles": False, "fichiers": False}), "")
    d = json.loads(z.read("donnees.json"))["documents"][0]
    assert (d["fichier"], d["emplacement"]) == ("", "")


def test_sauvegarde_avec_fichiers_drive_injoignable(client, db, copro_a, syndic_a, token_a, serveur):
    from tests.test_sauvegarde import COMPLETE
    _brancher(client, token_a)
    _deposer(client, token_a)
    serveur.panne = True
    r = client.post("/api/sauvegarde/export", json=COMPLETE, headers=auth(token_a))
    assert r.status_code == 503 and "injoignable" in r.json()["detail"]


def test_espace_de_stockage_compte_a_part_les_fichiers_du_drive(client, db, copro_a, syndic_a, token_a, serveur,
                                                                tmp_path, monkeypatch):
    from app.routes import documents
    monkeypatch.setattr(documents.settings, "upload_dir", str(tmp_path))
    _deposer(client, token_a, libelle="Local")
    _brancher(client, token_a)
    _deposer(client, token_a)
    serveur.panne = True                                               # l'écran ne dépend pas du drive
    d = client.get("/api/stockage", headers=auth(token_a)).json()["documents"]
    assert (d["nombre"], d["sur_le_drive"], d["octets"], d["introuvables"]) == (2, 1, 12, 0)
