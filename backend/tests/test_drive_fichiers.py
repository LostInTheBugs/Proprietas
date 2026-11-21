"""Drive de la copropriété, deuxième livraison : les fichiers existants et les fichiers renommés.

Règles :
- « Déplacer vers le drive » : les fichiers déposés avant le branchement partent sur le drive, rangés
  comme les nouveaux (dossier de la catégorie, « date d'ajout libellé.ext »). Par LOTS de 10 : l'écran
  rappelle tant qu'il en reste. Ordre : copie, contrôle de la taille, fiche mise à jour, puis suppression
  de l'original — une panne ne perd jamais un fichier. Un fichier absent du serveur est signalé, sa
  fiche ne change pas.
- « Rapatrier sur le serveur » : l'inverse, pour pouvoir débrancher le drive.
- Taille et empreinte SHA-256 du contenu sont relevées au dépôt et au déplacement.
- « Vérifier le drive » : documents dont le fichier manque, et fichiers du drive rattachés à aucun
  document (fichiers cachés ignorés).
- « Retrouver » : un document introuvable est relié au fichier du drive qui a exactement son contenu
  (même taille, même empreinte), où qu'il soit sous le dossier du drive — seulement si UN SEUL fichier
  correspond. Sinon, le syndic relie à la main ; un fichier déjà pris par un autre document est refusé.
- Réservé au syndic, isolé par copropriété, inscrit au journal d'audit.
"""
import hashlib
from datetime import date

import pytest

from app.models.audit import AuditLog
from app.models.document import Document
from app.services import drive_fichiers
from tests.conftest import _make_membre, auth
from tests.faux_webdav import FauxWebDAV  # noqa: F401
from tests.test_drive import AUJ, DOSSIER, _brancher, _deposer, serveur  # noqa: F401


@pytest.fixture()
def dossier_local(tmp_path, monkeypatch):
    from app.routes import documents
    monkeypatch.setattr(documents.settings, "upload_dir", str(tmp_path))
    return tmp_path


def _api(client, token, methode, chemin, **kw):
    return getattr(client, methode)(f"/api/drive/{chemin}", headers=auth(token), **kw)


# ---------------------------------------------------------------- déplacer, rapatrier
def test_deplacer_les_fichiers_existants(client, db, copro_a, syndic_a, token_a, serveur, dossier_local):
    a = _deposer(client, token_a, libelle="Contrat ascenseur", categorie="contrat", contenu=b"%PDF-contrat").json()
    b = _deposer(client, token_a, libelle="Facture EDF", contenu=b"%PDF-facture-edf").json()
    doc = db.get(Document, a["id"])
    doc.date_ajout = date(2024, 3, 5)
    db.commit()
    _brancher(client, token_a)
    assert client.get("/api/drive", headers=auth(token_a)).json()["documents_sur_le_serveur"] == 2
    r = _api(client, token_a, "post", "deplacer")
    assert r.status_code == 200, r.text
    assert r.json() == {"deplaces": 2, "introuvables": [], "restants": 0}
    # Rangés comme les nouveaux dépôts, à la date d'ajout du document.
    assert serveur.chemins() == [f"{DOSSIER}/Contrats/2024-03-05 Contrat ascenseur.pdf",
                                 f"{DOSSIER}/Factures/{AUJ} Facture EDF.pdf"]
    assert list(dossier_local.iterdir()) == []                       # plus rien sur le serveur
    db.expire_all()
    doc = db.get(Document, a["id"])
    assert (doc.emplacement, doc.fichier, doc.taille) == ("drive", "Contrats/2024-03-05 Contrat ascenseur.pdf", 12)
    assert doc.empreinte == hashlib.sha256(b"%PDF-contrat").hexdigest()
    assert client.get(f"/api/documents/{b['id']}/download", headers=auth(token_a)).content == b"%PDF-facture-edf"
    assert db.query(AuditLog).filter(AuditLog.action == "drive_deplacement").count() == 1
    # Rien à refaire.
    assert _api(client, token_a, "post", "deplacer").json()["deplaces"] == 0


def test_deplacement_par_lots(client, db, copro_a, syndic_a, token_a, serveur, dossier_local, monkeypatch):
    monkeypatch.setattr(drive_fichiers, "LOT_FICHIERS", 2)
    for n in range(5):
        _deposer(client, token_a, libelle=f"Doc {n}", contenu=b"%PDF-" + str(n).encode())
    _brancher(client, token_a)
    bilans = [_api(client, token_a, "post", "deplacer").json() for _ in range(3)]
    assert [(b["deplaces"], b["restants"]) for b in bilans] == [(2, 3), (2, 1), (1, 0)]
    assert len(serveur.chemins()) == 5


def test_fichier_absent_du_serveur_signale(client, db, copro_a, syndic_a, token_a, serveur, dossier_local):
    a = _deposer(client, token_a, libelle="Perdu").json()
    _deposer(client, token_a, libelle="Présent")
    (dossier_local / a["fichier"]).unlink()
    _brancher(client, token_a)
    bilan = _api(client, token_a, "post", "deplacer").json()
    assert bilan == {"deplaces": 1, "introuvables": [{"id": a["id"], "libelle": "Perdu"}], "restants": 0}
    db.expire_all()
    assert db.get(Document, a["id"]).emplacement == ""               # fiche inchangée


def test_panne_pendant_le_deplacement_ne_perd_rien(client, db, copro_a, syndic_a, token_a, serveur, dossier_local):
    for n in range(3):
        _deposer(client, token_a, libelle=f"Doc {n}", contenu=b"%PDF-" + str(n).encode())
    _brancher(client, token_a)
    serveur.plein = True                                             # le drive refuse l'écriture
    r = _api(client, token_a, "post", "deplacer")
    assert r.status_code == 503 and "plein" in r.json()["detail"]
    db.expire_all()
    assert db.query(Document).filter(Document.emplacement == "drive").count() == 0
    assert len(list(dossier_local.iterdir())) == 3                   # tout est encore sur le serveur
    serveur.plein = False
    assert _api(client, token_a, "post", "deplacer").json()["deplaces"] == 3


def test_copie_incomplete_refusee(client, db, copro_a, syndic_a, token_a, serveur, dossier_local, monkeypatch):
    _deposer(client, token_a, libelle="Doc", contenu=b"%PDF-0123456789")
    _brancher(client, token_a)
    from app.core import drive
    monkeypatch.setattr(drive.StockageWebDAV, "taille", lambda self, nom: 4)      # le drive n'a gardé que 4 octets
    r = _api(client, token_a, "post", "deplacer")
    assert r.status_code == 503 and "incomplète" in r.json()["detail"]
    assert serveur.chemins() == [] and len(list(dossier_local.iterdir())) == 1


def test_rapatrier_puis_debrancher(client, db, copro_a, syndic_a, token_a, serveur, dossier_local):
    _brancher(client, token_a)
    a = _deposer(client, token_a, contenu=b"%PDF-sur le drive").json()
    assert client.put("/api/drive", json={"type": ""}, headers=auth(token_a)).status_code == 409
    r = _api(client, token_a, "post", "rapatrier")
    assert r.json() == {"deplaces": 1, "introuvables": [], "restants": 0}
    assert serveur.chemins() == []
    db.expire_all()
    doc = db.get(Document, a["id"])
    assert doc.emplacement == "" and (dossier_local / doc.fichier).read_bytes() == b"%PDF-sur le drive"
    assert client.get(f"/api/documents/{a['id']}/download", headers=auth(token_a)).content == b"%PDF-sur le drive"
    assert client.put("/api/drive", json={"type": ""}, headers=auth(token_a)).status_code == 200
    assert db.query(AuditLog).filter(AuditLog.action == "drive_rapatriement").count() == 1


def test_sans_drive_branche(client, db, copro_a, syndic_a, token_a, serveur):
    for chemin in ("deplacer", "rapatrier", "retrouver"):
        assert _api(client, token_a, "post", chemin).status_code == 409
    assert _api(client, token_a, "get", "verification").status_code == 409


# ---------------------------------------------------------------- vérifier, retrouver, relier
def test_depot_releve_taille_et_empreinte(client, db, copro_a, syndic_a, token_a, serveur, dossier_local):
    a = _deposer(client, token_a, contenu=b"%PDF-abc").json()
    doc = db.get(Document, a["id"])
    assert (doc.taille, doc.empreinte) == (8, hashlib.sha256(b"%PDF-abc").hexdigest())


def test_verifier_le_drive(client, db, copro_a, syndic_a, token_a, serveur):
    _brancher(client, token_a)
    a = _deposer(client, token_a, libelle="Facture A", contenu=b"%PDF-aaa").json()
    _deposer(client, token_a, libelle="Facture B", contenu=b"%PDF-bbbb")
    v = _api(client, token_a, "get", "verification").json()
    assert v == {"verifies": 2, "introuvables": [], "non_rattaches": []}
    # Sur le drive : A est renommé, un fichier étranger et un fichier caché apparaissent.
    serveur.renommer(f"{DOSSIER}/{a['fichier']}", f"{DOSSIER}/Factures/EDF novembre.pdf")
    serveur.fichiers[f"{DOSSIER}/Divers/photo.jpg"] = b"x" * 9
    serveur.dossiers.add(f"{DOSSIER}/Divers")
    serveur.fichiers[f"{DOSSIER}/.cache"] = b"y"
    v = _api(client, token_a, "get", "verification").json()
    assert v["introuvables"] == [{"id": a["id"], "libelle": "Facture A", "categorie": "facture",
                                  "fichier": a["fichier"], "retrouvable": True}]
    assert v["non_rattaches"] == [{"chemin": "Divers/photo.jpg", "taille": 9},
                                  {"chemin": "Factures/EDF novembre.pdf", "taille": 8}]


@pytest.mark.parametrize("minuscules,complet", [(True, False), (False, False), (True, True)])
def test_liste_du_drive_selon_le_serveur(client, db, copro_a, syndic_a, token_a, serveur, minuscules, complet):
    """Adresses renvoyées en %c3%a9 ou %C3%A9, relatives ou complètes : même résultat."""
    serveur.href_minuscules, serveur.href_complet = minuscules, complet
    _brancher(client, token_a)
    a = _deposer(client, token_a, libelle="Reçu d'été", contenu=b"%PDF-aaa").json()
    assert a["fichier"] == f"Factures/{AUJ} Reçu d'été.pdf"
    assert _api(client, token_a, "get", "verification").json() == {"verifies": 1, "introuvables": [], "non_rattaches": []}


def test_retrouver_un_fichier_renomme_ou_deplace(client, db, copro_a, syndic_a, token_a, serveur):
    _brancher(client, token_a)
    a = _deposer(client, token_a, libelle="Facture A", contenu=b"%PDF-contenu de A").json()
    b = _deposer(client, token_a, libelle="Facture B", contenu=b"%PDF-contenu de B").json()
    serveur.renommer(f"{DOSSIER}/{a['fichier']}", f"{DOSSIER}/Archives/2026/EDF.pdf")       # déplacé ET renommé
    serveur.fichiers[f"{DOSSIER}/Factures/leurre.pdf"] = b"contenu de X"                    # même taille, autre contenu
    r = _api(client, token_a, "post", "retrouver")
    assert r.status_code == 200, r.text
    assert r.json()["relies"] == [{"id": a["id"], "libelle": "Facture A", "ancien": a["fichier"],
                                   "nouveau": "Archives/2026/EDF.pdf"}]
    assert r.json()["introuvables"] == []
    assert client.get(f"/api/documents/{a['id']}/download", headers=auth(token_a)).content == b"%PDF-contenu de A"
    assert client.get(f"/api/documents/{b['id']}/download", headers=auth(token_a)).content == b"%PDF-contenu de B"
    detail = db.query(AuditLog).filter(AuditLog.action == "drive_fichier_relie").one().detail
    assert "Archives/2026/EDF.pdf" in detail and "contenu" in detail


def test_retrouver_ne_devine_pas(client, db, copro_a, syndic_a, token_a, serveur):
    _brancher(client, token_a)
    a = _deposer(client, token_a, libelle="Facture A", contenu=b"%PDF-meme contenu").json()
    # Le fichier a disparu ; deux copies identiques traînent : on ne choisit pas à la place du syndic.
    del serveur.fichiers[f"{DOSSIER}/{a['fichier']}"]
    serveur.fichiers[f"{DOSSIER}/Factures/copie 1.pdf"] = b"%PDF-meme contenu"
    serveur.fichiers[f"{DOSSIER}/Factures/copie 2.pdf"] = b"%PDF-meme contenu"
    r = _api(client, token_a, "post", "retrouver").json()
    assert r["relies"] == [] and [i["id"] for i in r["introuvables"]] == [a["id"]]
    # Fichier modifié (autre contenu) : pas retrouvé non plus.
    serveur.fichiers.clear()
    serveur.fichiers[f"{DOSSIER}/Factures/modifié.pdf"] = b"autre  texte"
    assert _api(client, token_a, "post", "retrouver").json()["relies"] == []


def test_relier_a_la_main(client, db, copro_a, syndic_a, token_a, serveur):
    _brancher(client, token_a)
    a = _deposer(client, token_a, libelle="Facture A", contenu=b"%PDF-ancien").json()
    b = _deposer(client, token_a, libelle="Facture B", contenu=b"%PDF-bbb").json()
    del serveur.fichiers[f"{DOSSIER}/{a['fichier']}"]
    serveur.fichiers[f"{DOSSIER}/Factures/rescanné.pdf"] = b"nouveau scan"
    corps = {"document_id": a["id"], "chemin": "Factures/rescanné.pdf"}
    r = _api(client, token_a, "post", "relier", json=corps)
    assert r.status_code == 200 and r.json() == {"ok": True, "fichier": "Factures/rescanné.pdf"}
    db.expire_all()
    doc = db.get(Document, a["id"])
    assert (doc.taille, doc.empreinte) == (12, hashlib.sha256(b"nouveau scan").hexdigest())
    assert client.get(f"/api/documents/{a['id']}/download", headers=auth(token_a)).content == b"nouveau scan"
    # Refus : fichier d'un autre document, fichier absent, chemin qui sort du dossier.
    for chemin, message in ((b["fichier"], "déjà celui"), ("Factures/absent.pdf", "n'existe pas"), ("../x.pdf", "invalide")):
        r = _api(client, token_a, "post", "relier", json={"document_id": a["id"], "chemin": chemin})
        assert r.status_code == 422 and message in r.json()["detail"], r.text


def test_reserve_au_syndic_et_isole(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b, serveur):
    from app.core.security import create_access_token
    _brancher(client, token_a)
    a = _deposer(client, token_a).json()
    membre = create_access_token(_make_membre(db, "m@test.fr", copro_a).id, copro_a.id)
    for methode, chemin in (("post", "deplacer"), ("post", "rapatrier"), ("get", "verification"), ("post", "retrouver")):
        assert _api(client, membre, methode, chemin).status_code == 403
    assert _api(client, membre, "post", "relier", json={"document_id": a["id"], "chemin": "x"}).status_code == 403
    # L'autre copropriété n'a pas de drive, et ne peut pas toucher à ce document.
    assert _api(client, token_b, "get", "verification").status_code == 409
    _brancher(client, token_b, dossier="Proprietas/Résidence B")
    assert _api(client, token_b, "post", "relier", json={"document_id": a["id"], "chemin": a["fichier"]}).status_code == 404
    assert _api(client, token_b, "get", "verification").json()["non_rattaches"] == []
