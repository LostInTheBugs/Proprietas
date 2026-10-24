"""Upload de documents : la limite de taille s'applique PENDANT la réception, pas après.

Avant : `await fichier.read()` chargeait le fichier ENTIER en mémoire, puis comparait sa
taille à COPRO_UPLOAD_MAX_MB. Un envoi de plusieurs centaines de Mo occupait autant de
RAM (ionos02 : 848 Mo au total) avant d'être refusé.
Maintenant :
- une requête dont l'en-tête Content-Length dépasse déjà la limite est refusée d'emblée
  (413), sans lire le corps ;
- sinon le fichier est copié sur disque par blocs de 1 Mo, et la copie s'arrête dès que la
  limite est franchie : rien ne reste sur le disque.
"""
import os

import pytest
from starlette.datastructures import UploadFile

from app.routes import documents as docs
from tests.conftest import auth

# Les réglages LUS PAR LA ROUTE (et par le garde Content-Length de main.py) : d'autres
# tests vident le cache de get_settings(), qui peut alors renvoyer un autre objet.


def _fichiers():
    d = docs.settings.upload_dir
    return set(os.listdir(d)) if os.path.isdir(d) else set()


def _envoyer(client, token_a, contenu: bytes):
    return client.post("/api/documents", data={"categorie": "autre", "libelle": "Test"},
                       files={"fichier": ("doc.pdf", contenu, "application/pdf")},
                       headers=auth(token_a))


@pytest.fixture()
def lectures(monkeypatch):
    """Enregistre la taille demandée à chaque UploadFile.read()."""
    tailles = []
    original = UploadFile.read

    async def espion(self, size=-1):
        tailles.append(size)
        return await original(self, size)
    monkeypatch.setattr(UploadFile, "read", espion)
    return tailles


def test_fichier_accepte_intact_et_lu_par_blocs(client, token_a, lectures):
    contenu = os.urandom(2_500_000)                        # 2,5 Mo : plusieurs blocs
    avant = _fichiers()
    r = _envoyer(client, token_a, contenu)
    assert r.status_code == 200, r.text
    nouveaux = _fichiers() - avant
    assert len(nouveaux) == 1
    with open(os.path.join(docs.settings.upload_dir, nouveaux.pop()), "rb") as f:
        assert f.read() == contenu
    assert lectures and all(0 < t <= 1024 * 1024 for t in lectures)   # jamais read() sans taille


def test_depassement_pendant_la_copie_413_et_rien_sur_le_disque(client, token_a, monkeypatch):
    monkeypatch.setattr(docs.settings, "upload_max_mb", 1.5)          # limite 1,5 Mo
    avant = _fichiers()
    # 2 Mo : Content-Length (≈ 2 Mo) reste sous limite + marge → c'est la copie qui coupe
    r = _envoyer(client, token_a, b"x" * 2_000_000)
    assert r.status_code == 413
    assert "trop volumineux" in r.json()["detail"]
    assert _fichiers() == avant


def test_content_length_trop_grand_refuse_avant_lecture(client, token_a, monkeypatch, lectures):
    monkeypatch.setattr(docs.settings, "upload_max_mb", 0.5)          # 0,5 Mo
    r = _envoyer(client, token_a, b"x" * 3_000_000)                    # 3 Mo > 0,5 + marge 1 Mo
    assert r.status_code == 413
    assert r.json()["detail"].startswith("Requête trop volumineuse")
    assert lectures == []                                              # le fichier n'a pas été lu
