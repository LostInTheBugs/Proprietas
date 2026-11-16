"""Drive de la copropriété, troisième livraison : la sauvegarde déposée sur le drive.

Choix de Fred (16/11/2026) : sauvegarde hebdomadaire automatique, chiffrée par un mot de passe saisi une
fois dans Réglages, plus un bouton « Sauvegarder maintenant ».

Règles :
- fichier « <dossier du drive>/Sauvegardes/Sauvegarde AAAA-MM-JJ HHhMM.zip », toujours chiffré (AES-256) ;
  mot de passe de 10 caractères au moins, chiffré en base, jamais renvoyé, jamais dans l'archive ;
- contenu : toutes les données, données personnelles comprises, et les fichiers encore sur le serveur ;
  les fichiers déjà sur le drive ne sont pas recopiés : leurs fiches gardent leur chemin, et la
  copropriété le dossier de son drive (ni adresse, ni identifiant, ni mot de passe) ;
- automatique : quand la dernière sauvegarde réussie a 7 jours ; après un échec, nouvel essai au plus
  toutes les 6 heures, et la raison s'affiche dans Réglages ;
- les 8 plus récentes sont gardées ; seuls les fichiers nommés par Proprietas sont supprimés ;
- restauration : importer l'archive crée une copropriété dont les fichiers du drive sont « à rebrancher » ;
  une fois le drive rebranché sur le même dossier, ils sont de nouveau lisibles ;
- deux copropriétés d'une même instance ne peuvent pas partager un dossier du drive ;
- sans drive branché, la fiche d'un document du drive peut être supprimée (le fichier reste sur le drive) ;
- le dossier Sauvegardes n'apparaît pas dans les « fichiers rattachés à aucun document ».
"""
import io
import json
from datetime import datetime, timedelta

import pyzipper
import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.core.security import create_access_token
from app.models.audit import AuditLog
from app.models.copropriete import Copropriete
from app.models.document import Document
from app.services import drive_sauvegarde
from tests.conftest import _make_membre, auth
from tests.test_drive import AUJ, DOSSIER, _brancher, _deposer, _reglages, serveur  # noqa: F401
from tests.test_drive_fichiers import dossier_local  # noqa: F401
from tests.test_sauvegarde import _import

MDP = "sauvegarde-2026"
T0 = datetime(2026, 11, 17, 3, 30)


def _regler(client, token, auto=True, mot_de_passe=MDP):
    return client.put("/api/drive/sauvegarde", json={"auto": auto, "mot_de_passe": mot_de_passe}, headers=auth(token))


def _maintenant(client, token):
    return client.post("/api/drive/sauvegarde/maintenant", headers=auth(token))


def _archives(serveur):
    return [c for c in serveur.chemins() if c.startswith(f"{DOSSIER}/Sauvegardes/")]


def _ouvrir(contenu, mot_de_passe=MDP):
    z = pyzipper.AESZipFile(io.BytesIO(contenu))
    z.setpassword(mot_de_passe.encode())
    return z


# ---------------------------------------------------------------- réglages
def test_regler_la_sauvegarde(client, db, copro_a, syndic_a, token_a, serveur):
    assert _regler(client, token_a).status_code == 409                       # pas de drive branché
    _brancher(client, token_a)
    assert _regler(client, token_a, mot_de_passe="court").status_code == 422
    assert _regler(client, token_a, mot_de_passe="").status_code == 422      # automatique sans mot de passe
    r = _regler(client, token_a)
    assert r.status_code == 200, r.text
    s = r.json()["sauvegarde"]
    assert (s["auto"], s["mot_de_passe_defini"], s["derniere"], s["erreur"]) == (True, True, None, "")
    assert s["prochaine"] is not None and MDP not in r.text
    brut = db.execute(text("SELECT drive_sauvegarde_password FROM coproprietes WHERE id = :i"), {"i": copro_a.id}).scalar()
    assert brut.startswith("enc:v1:")
    # Mot de passe vide : on garde l'ancien ; on peut couper l'automatique.
    s = _regler(client, token_a, auto=False, mot_de_passe="").json()["sauvegarde"]
    assert (s["auto"], s["mot_de_passe_defini"], s["prochaine"]) == (False, True, None)
    db.expire_all()
    assert db.get(Copropriete, copro_a.id).drive_sauvegarde_password == MDP
    assert db.query(AuditLog).filter(AuditLog.action == "drive_sauvegarde_reglee").count() == 2


def test_reserve_au_syndic(client, db, copro_a, syndic_a, token_a, serveur):
    _brancher(client, token_a)
    membre = create_access_token(_make_membre(db, "m@test.fr", copro_a).id, copro_a.id)
    assert _regler(client, membre).status_code == 403
    assert _maintenant(client, membre).status_code == 403
    assert client.get("/api/drive/sauvegardes", headers=auth(membre)).status_code == 403


# ---------------------------------------------------------------- sauvegarder maintenant
def test_sauvegarder_maintenant(client, db, copro_a, syndic_a, token_a, serveur, dossier_local):
    local = _deposer(client, token_a, libelle="Resté sur le serveur", contenu=b"local").json()
    _brancher(client, token_a)
    sur_drive = _deposer(client, token_a, libelle="Sur le drive", contenu=b"drive").json()
    assert _maintenant(client, token_a).status_code == 422                   # pas encore de mot de passe
    _regler(client, token_a, auto=False)
    r = _maintenant(client, token_a)
    assert r.status_code == 200, r.text
    [archive] = _archives(serveur)
    assert r.json()["fichier"] == archive[len(DOSSIER) + 1:] and drive_sauvegarde.NOM.match(archive.rpartition("/")[2])
    assert r.json()["etat"]["sauvegarde"]["derniere"] is not None
    contenu = serveur.fichiers[archive]
    with pytest.raises(RuntimeError):                                        # illisible sans le mot de passe
        pyzipper.AESZipFile(io.BytesIO(contenu)).read("donnees.json")
    z = _ouvrir(contenu)
    donnees = json.loads(z.read("donnees.json"))
    # Données personnelles comprises.
    assert syndic_a.email in {u["email"] for u in donnees["users"]}
    # Le fichier du serveur est dans l'archive ; celui du drive n'y est pas, sa fiche garde son chemin.
    docs = {d["libelle"]: d for d in donnees["documents"]}
    assert z.read(f"documents/{local['fichier']}") == b"local"
    assert (docs["Sur le drive"]["emplacement"], docs["Sur le drive"]["fichier"]) == ("drive", sur_drive["fichier"])
    assert not [n for n in z.namelist() if "Sur le drive" in n]
    assert docs["Resté sur le serveur"]["emplacement"] == ""
    # Du drive, seul le dossier est retenu ; aucun secret.
    c = donnees["coproprietes"][0]
    assert c["drive_dossier"] == DOSSIER
    assert not {"drive_url", "drive_user", "drive_password", "drive_sauvegarde_password", "drive_type"} & set(c)
    assert MDP not in json.dumps(donnees) and "secret-drive" not in json.dumps(donnees)
    assert json.loads(z.read("manifest.json"))["liens_drive"] is True
    assert db.query(AuditLog).filter(AuditLog.action == "drive_sauvegarde").count() == 1
    # Liste des sauvegardes, et rien dans les « fichiers rattachés à aucun document ».
    liste = client.get("/api/drive/sauvegardes", headers=auth(token_a)).json()
    assert [s["fichier"] for s in liste] == [archive[len(DOSSIER) + 1:]] and liste[0]["taille"] == len(contenu)
    assert client.get("/api/drive/verification", headers=auth(token_a)).json()["non_rattaches"] == []


def test_la_sauvegarde_telechargee_ne_change_pas(client, db, copro_a, syndic_a, token_a, serveur):
    """La sauvegarde à télécharger reste autonome : fichiers du drive dedans, aucune trace du drive."""
    from tests.test_sauvegarde import COMPLETE, _export, _ouvrir as ouvrir
    _brancher(client, token_a)
    doc = _deposer(client, token_a).json()
    z = ouvrir(_export(client, token_a, COMPLETE))
    donnees = json.loads(z.read("donnees.json"))
    assert z.read(f"documents/{doc['fichier']}") == b"%PDF-1 essai"
    assert donnees["documents"][0]["emplacement"] == "" and "drive_dossier" not in donnees["coproprietes"][0]


def test_les_plus_anciennes_sont_supprimees(client, db, copro_a, syndic_a, token_a, serveur, monkeypatch):
    from app.routes import documents
    _brancher(client, token_a)
    _regler(client, token_a, auto=False)
    monkeypatch.setattr(drive_sauvegarde, "GARDER", 2)
    serveur.fichiers[f"{DOSSIER}/Sauvegardes/mes notes.txt"] = b"a moi"      # pas un fichier de Proprietas
    db.expire_all()
    copro = db.get(Copropriete, copro_a.id)
    st = documents._drive(copro)
    bilans = [drive_sauvegarde.sauvegarder(db, copro, documents._stockage(), st, T0 + timedelta(days=7 * n))
              for n in range(3)]
    assert [b["supprimees"] for b in bilans] == [0, 0, 1]
    assert _archives(serveur) == [f"{DOSSIER}/Sauvegardes/Sauvegarde 2026-11-24 03h30.zip",
                                  f"{DOSSIER}/Sauvegardes/Sauvegarde 2026-12-01 03h30.zip",
                                  f"{DOSSIER}/Sauvegardes/mes notes.txt"]
    # Deux sauvegardes la même minute : aucune n'écrase l'autre.
    b = drive_sauvegarde.sauvegarder(db, copro, documents._stockage(), st, T0 + timedelta(days=14))
    assert b["fichier"] == "Sauvegardes/Sauvegarde 2026-12-01 03h30 (2).zip"


# ---------------------------------------------------------------- automatique
def test_sauvegarde_automatique_chaque_semaine(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b,
                                               serveur):
    _brancher(client, token_a)
    _regler(client, token_a)
    _brancher(client, token_b, dossier="Proprietas/Résidence B")              # branchée, sans automatique
    assert drive_sauvegarde.run_sauvegardes_drive(db, T0) == {"sauvegardes": 1, "echecs": 0}
    assert len(_archives(serveur)) == 1
    # Pas avant 7 jours.
    assert drive_sauvegarde.run_sauvegardes_drive(db, T0 + timedelta(days=6, hours=23)) == {"sauvegardes": 0, "echecs": 0}
    assert drive_sauvegarde.run_sauvegardes_drive(db, T0 + timedelta(days=7)) == {"sauvegardes": 1, "echecs": 0}
    assert len(_archives(serveur)) == 2
    s = client.get("/api/drive", headers=auth(token_a)).json()["sauvegarde"]
    assert (s["derniere"], s["prochaine"]) == ("2026-11-24T03:30", "2026-12-01T03:30")


def test_echec_garde_la_raison_et_reessaie_plus_tard(client, db, copro_a, syndic_a, token_a, serveur):
    _brancher(client, token_a)
    _regler(client, token_a)
    serveur.panne = True
    assert drive_sauvegarde.run_sauvegardes_drive(db, T0) == {"sauvegardes": 0, "echecs": 1}
    s = client.get("/api/drive", headers=auth(token_a)).json()["sauvegarde"]
    assert "17/11/2026 03:30" in s["erreur"] and "injoignable" in s["erreur"] and s["derniere"] is None
    # Pas de nouvel essai avant 6 heures.
    assert drive_sauvegarde.run_sauvegardes_drive(db, T0 + timedelta(hours=5)) == {"sauvegardes": 0, "echecs": 0}
    serveur.panne = False
    assert drive_sauvegarde.run_sauvegardes_drive(db, T0 + timedelta(hours=6)) == {"sauvegardes": 1, "echecs": 0}
    s = client.get("/api/drive", headers=auth(token_a)).json()["sauvegarde"]
    assert s["erreur"] == "" and s["derniere"] == "2026-11-17T09:30"


def test_automatique_coupe(client, db, copro_a, syndic_a, token_a, serveur, monkeypatch):
    _brancher(client, token_a)
    _regler(client, token_a)
    monkeypatch.setattr(get_settings(), "drive_actif", False)                # fonction retirée de l'instance
    assert drive_sauvegarde.run_sauvegardes_drive(db, T0) == {"sauvegardes": 0, "echecs": 0}
    monkeypatch.setattr(get_settings(), "drive_actif", True)
    # Débrancher le drive coupe la sauvegarde automatique.
    client.put("/api/drive", json={"type": ""}, headers=auth(token_a))
    db.expire_all()
    assert db.get(Copropriete, copro_a.id).drive_sauvegarde_auto is False
    assert drive_sauvegarde.run_sauvegardes_drive(db, T0) == {"sauvegardes": 0, "echecs": 0}
    assert _archives(serveur) == []


# ---------------------------------------------------------------- restauration
def test_restaurer_depuis_le_drive(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b, serveur,
                                   dossier_local):
    _deposer(client, token_a, libelle="Resté sur le serveur", contenu=b"local")
    _brancher(client, token_a)
    doc = _deposer(client, token_a, libelle="Sur le drive", contenu=b"drive").json()
    _regler(client, token_a, auto=False)
    _maintenant(client, token_a)
    [archive] = _archives(serveur)
    # Sur un autre compte (comme sur un nouveau serveur) : import de l'archive prise sur le drive.
    r = _import(client, token_b, serveur.fichiers[archive], mot_de_passe=MDP)
    assert r.status_code == 200, r.text
    assert r.json()["documents_sur_le_drive"] == 1
    assert any("rebranchez-le" in a and DOSSIER in a for a in r.json()["avertissements"])
    nid = r.json()["copropriete_id"]
    tok = client.post(f"/api/auth/switch-copro/{nid}", headers=auth(token_b)).json()["access_token"]
    copie = {d.libelle: d for d in db.query(Document).filter(Document.copropriete_id == nid)}
    assert (copie["Sur le drive"].emplacement, copie["Sur le drive"].fichier) == ("drive", doc["fichier"])
    assert copie["Sur le drive"].empreinte and copie["Resté sur le serveur"].emplacement == ""
    etat = client.get("/api/drive", headers=auth(tok)).json()
    assert (etat["type"], etat["dossier"], etat["documents_sur_le_drive"]) == ("", DOSSIER, 1)
    assert etat["sauvegarde"] == {"auto": False, "mot_de_passe_defini": False, "derniere": None, "prochaine": None,
                                  "erreur": "", "gardees": 8}
    # Tant que le drive n'est pas rebranché : explication claire, et le fichier du serveur est lisible.
    r = client.get(f"/api/documents/{copie['Sur le drive'].id}/download", headers=auth(tok))
    assert r.status_code == 503 and "plus branché" in r.json()["detail"]
    assert client.get(f"/api/documents/{copie['Resté sur le serveur'].id}/download", headers=auth(tok)).content == b"local"
    # L'original est encore branché sur ce dossier : la copie ne peut pas le prendre.
    r = client.put("/api/drive", json=_reglages(), headers=auth(tok))
    assert r.status_code == 409 and "autre copropriété" in r.json()["detail"]
    r = client.put("/api/drive", json=_reglages(dossier="Proprietas"), headers=auth(tok))    # dossier parent : non plus
    assert r.status_code == 409
    # L'ancien serveur n'existe plus : la copropriété restaurée rebranche le drive, ses fichiers reviennent.
    db.execute(text("UPDATE coproprietes SET drive_type = '' WHERE id = :i"), {"i": copro_a.id})
    db.commit()
    assert client.put("/api/drive", json=_reglages(), headers=auth(tok)).status_code == 200
    assert client.get(f"/api/documents/{copie['Sur le drive'].id}/download", headers=auth(tok)).content == b"drive"


def test_supprimer_une_fiche_sans_drive_branche(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b,
                                                serveur):
    _brancher(client, token_a)
    doc = _deposer(client, token_a).json()
    _regler(client, token_a, auto=False)
    _maintenant(client, token_a)
    r = _import(client, token_b, serveur.fichiers[_archives(serveur)[0]], mot_de_passe=MDP)
    tok = client.post(f"/api/auth/switch-copro/{r.json()['copropriete_id']}", headers=auth(token_b)).json()["access_token"]
    copie = db.query(Document).filter(Document.copropriete_id == r.json()["copropriete_id"]).one()
    assert client.delete(f"/api/documents/{copie.id}", headers=auth(tok)).status_code == 200
    assert f"{DOSSIER}/{doc['fichier']}" in serveur.chemins()                  # le fichier de l'original est intact


def test_archive_forgee(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b, serveur):
    """Chemins de drive invalides dans une archive : ignorés à l'import."""
    import zipfile
    from tests.test_sauvegarde import _export
    z = zipfile.ZipFile(io.BytesIO(_export(client, token_a, {})))
    donnees = json.loads(z.read("donnees.json"))
    donnees["coproprietes"][0]["drive_dossier"] = "../../ailleurs"
    donnees["documents"] = [{"id": 1, "copropriete_id": donnees["coproprietes"][0]["id"], "categorie": "autre",
                             "libelle": "piège", "fichier": "../../secret.pdf", "emplacement": "drive",
                             "date_ajout": AUJ}]
    sortie = io.BytesIO()
    with zipfile.ZipFile(sortie, "w") as z2:
        for nom in z.namelist():
            z2.writestr(nom, json.dumps(donnees) if nom == "donnees.json" else z.read(nom))
    r = _import(client, token_b, sortie.getvalue(), mot_de_passe="")
    assert r.status_code == 200, r.text
    nid = r.json()["copropriete_id"]
    doc = db.query(Document).filter(Document.copropriete_id == nid).one()
    assert (doc.fichier, doc.emplacement) == ("", "") and not db.get(Copropriete, nid).drive_dossier
