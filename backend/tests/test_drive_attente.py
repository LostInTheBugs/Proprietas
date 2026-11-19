"""Dépôts mis en attente quand le drive est injoignable (option COPRO_DRIVE_ATTENTE_MO, demande de Fred, 19/11/2026).

Constat de l'exercice de reprise : pendant une panne du drive, un document déposé était refusé (503).
Option de l'instance : COPRO_DRIVE_ATTENTE_MO = plafond en Mo des fichiers en attente, toutes copropriétés
confondues ; 50 Mo par défaut (choix de Fred : « ça reste du cache, mais modifiable ») ; 0 = désactivé.
- drive injoignable et place suffisante : le fichier est gardé sur le serveur, document « en attente » (lisible) ;
- le planificateur (toutes les 5 min) ou le bouton « Ranger maintenant » le range sur le drive à son retour ;
- plafond atteint : refus, avec la raison ; débrancher le drive : les dépôts en attente restent sur le serveur.
"""
import pytest

from app.core.config import get_settings
from app.models.document import Document
from app.services import drive_fichiers
from tests.conftest import auth
from tests.test_drive import AUJ, DOSSIER, _brancher, _deposer, serveur  # noqa: F401


@pytest.fixture()
def attente(monkeypatch):
    monkeypatch.setattr(get_settings(), "drive_attente_mo", 0.05)       # ~52 Ko pour toute l'instance
    return get_settings()


def test_50_mo_par_defaut_et_0_desactive(client, db, copro_a, syndic_a, token_a, serveur, monkeypatch):
    assert get_settings().drive_attente_mo == 50
    monkeypatch.setattr(get_settings(), "drive_attente_mo", 0)
    _brancher(client, token_a)
    serveur.panne = True
    r = _deposer(client, token_a)
    assert r.status_code == 503 and "injoignable" in r.json()["detail"] and "place" not in r.json()["detail"]
    assert db.query(Document).count() == 0


def test_depot_en_attente_puis_range(client, db, copro_a, syndic_a, token_a, serveur, attente):
    _brancher(client, token_a)
    serveur.panne = True
    r = _deposer(client, token_a, contenu=b"%PDF-1 pendant la panne")
    assert r.status_code == 200 and r.json()["emplacement"] == "attente"
    doc = r.json()
    # Lisible tout de suite, depuis le serveur.
    assert client.get(f"/api/documents/{doc['id']}/download", headers=auth(token_a)).content == b"%PDF-1 pendant la panne"
    etat = client.get("/api/drive", headers=auth(token_a)).json()
    assert etat["en_attente"] == {"nombre": 1, "octets": 23, "plafond_mo": 0.05}
    # Toujours en panne : le passage du planificateur ne perd rien.
    db.expire_all()                  # le planificateur a sa propre session : il voit le drive branché
    assert drive_fichiers.run_ranger_en_attente(db) == {"ranges": 0, "en_attente": 1}
    assert client.post("/api/drive/ranger-attente", headers=auth(token_a)).status_code == 503
    serveur.panne = False
    assert drive_fichiers.run_ranger_en_attente(db) == {"ranges": 1, "en_attente": 0}
    db.expire_all()
    d = db.get(Document, doc["id"])
    assert d.emplacement == "drive" and d.fichier == f"Factures/{AUJ} Facture d'électricité.pdf"
    assert serveur.fichiers[f"{DOSSIER}/{d.fichier}"] == b"%PDF-1 pendant la panne"
    assert client.get(f"/api/documents/{doc['id']}/download", headers=auth(token_a)).content == b"%PDF-1 pendant la panne"
    assert client.get("/api/drive", headers=auth(token_a)).json()["en_attente"]["nombre"] == 0


def test_bouton_ranger_maintenant(client, db, copro_a, syndic_a, token_a, serveur, attente):
    _brancher(client, token_a)
    serveur.panne = True
    _deposer(client, token_a, libelle="Devis", categorie="devis")
    serveur.panne = False
    r = client.post("/api/drive/ranger-attente", headers=auth(token_a))
    assert r.status_code == 200 and r.json()["deplaces"] == 1 and r.json()["restants"] == 0
    assert db.query(Document).one().fichier == f"Devis/{AUJ} Devis.pdf"


def test_plafond_de_l_instance(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b, serveur, attente):
    _brancher(client, token_a)
    _brancher(client, token_b, dossier="Proprietas/Résidence B")
    serveur.panne = True
    assert _deposer(client, token_a, contenu=b"x" * 30_000).json()["emplacement"] == "attente"
    # Le plafond vaut pour toute l'instance : B ne peut plus mettre 30 Ko en attente.
    r = _deposer(client, token_b, contenu=b"y" * 30_000)
    assert r.status_code == 503 and "place réservée pleine" in r.json()["detail"]
    assert _deposer(client, token_b, contenu=b"y" * 10_000).json()["emplacement"] == "attente"


def test_debrancher_garde_les_depots_sur_le_serveur(client, db, copro_a, syndic_a, token_a, serveur, attente):
    _brancher(client, token_a)
    serveur.panne = True
    doc = _deposer(client, token_a).json()
    serveur.panne = False
    assert client.put("/api/drive", json={"type": ""}, headers=auth(token_a)).status_code == 200
    db.expire_all()
    assert db.get(Document, doc["id"]).emplacement == ""
    assert client.get(f"/api/documents/{doc['id']}/download", headers=auth(token_a)).content == b"%PDF-1 essai"
    assert drive_fichiers.run_ranger_en_attente(db) == {"ranges": 0, "en_attente": 0}


def test_sauvegarde_avec_un_depot_en_attente(client, db, copro_a, syndic_a, token_a, serveur, attente):
    import io
    import pyzipper
    _brancher(client, token_a)
    serveur.panne = True
    _deposer(client, token_a, contenu=b"%PDF-1 en attente")
    r = client.post("/api/sauvegarde/export", json={"mot_de_passe": "sauvegarde-2026", "fichiers": True},
                    headers=auth(token_a))
    assert r.status_code == 200
    with pyzipper.AESZipFile(io.BytesIO(r.content)) as z:
        z.setpassword(b"sauvegarde-2026")
        assert b"%PDF-1 en attente" in [z.read(n) for n in z.namelist() if n.startswith("documents/")]
