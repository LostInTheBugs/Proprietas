"""Espace de stockage affiché dans Réglages.

Règles retenues :
- le syndic voit la place prise par les documents de SA copropriété (nombre, octets ; un fichier
  introuvable est compté à part, pas dans les octets) ;
- l'administrateur de l'instance voit en plus le disque du serveur (total, utilisé, libre), la
  taille de la base et la place prise par tous les documents de l'instance ;
- avec un stockage S3, pas d'espace libre pour les documents : seulement l'espace utilisé ;
- réservé au syndic (403 pour un copropriétaire).
"""
from datetime import date

import pytest

from app.core import stockage as stk
from app.core.security import create_access_token
from app.models.document import Document
from app.routes import documents as docs
from tests.conftest import _make_membre, auth
from tests.test_stockage import BUCKET  # noqa: F401 — même bucket simulé
from tests.test_stockage import s3  # noqa: F401 — fixture

URL = "/api/stockage"


def _envoyer(client, token, contenu, libelle="Facture"):
    r = client.post("/api/documents", data={"categorie": "facture", "libelle": libelle},
                    files={"fichier": ("f.pdf", contenu, "application/pdf")}, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def test_syndic_voit_les_documents_de_sa_copropriete(client, db, copro_a, copro_b, syndic_a, syndic_b,
                                                    token_a, token_b):
    _envoyer(client, token_a, b"x" * 10)
    _envoyer(client, token_a, b"y" * 20)
    _envoyer(client, token_b, b"z" * 1000)               # autre copropriété : pas compté
    r = client.get(URL, headers=auth(token_a))
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["stockage"] == "local"
    assert e["documents"] == {"nombre": 2, "octets": 30, "introuvables": 0}
    assert e["instance"] is None                          # pas administrateur de l'instance


def test_fichier_introuvable_compte_a_part(client, db, copro_a, syndic_a, token_a):
    _envoyer(client, token_a, b"x" * 10)
    db.add(Document(copropriete_id=copro_a.id, libelle="Perdu", fichier="absent.pdf", date_ajout=date.today()))
    db.add(Document(copropriete_id=copro_a.id, libelle="Sans fichier", fichier="", date_ajout=date.today()))
    db.commit()
    e = client.get(URL, headers=auth(token_a)).json()
    assert e["documents"] == {"nombre": 3, "octets": 10, "introuvables": 1}


def test_administrateur_de_l_instance_voit_le_serveur(client, db, copro_a, copro_b, syndic_a, syndic_b,
                                                     token_a, token_b):
    syndic_a.is_instance_admin = True
    db.commit()
    _envoyer(client, token_a, b"x" * 10)
    _envoyer(client, token_b, b"z" * 1000)
    e = client.get(URL, headers=auth(token_a)).json()
    inst = e["instance"]
    d = inst["disque"]
    assert d["total"] > 0 and 0 <= d["libre"] <= d["total"] and d["utilise"] == d["total"] - d["libre"]
    assert inst["base_octets"] > 0
    assert inst["documents_octets"] >= 1010               # toutes les copropriétés
    assert e["documents"]["octets"] == 10                 # la copropriété active seulement


def test_reserve_au_syndic(client, db, copro_a, syndic_a):
    membre = _make_membre(db, "m@test.fr", copro_a)
    assert client.get(URL, headers=auth(create_access_token(membre.id, copro_a.id))).status_code == 403


def test_stockage_s3_espace_utilise_seulement(client, db, copro_a, syndic_a, token_a, s3, monkeypatch):  # noqa: F811
    monkeypatch.setattr(docs, "_stockage", lambda: s3)
    syndic_a.is_instance_admin = True
    db.commit()
    _envoyer(client, token_a, b"x" * 42)
    e = client.get(URL, headers=auth(token_a)).json()
    assert e["stockage"] == "s3"
    assert e["documents"] == {"nombre": 1, "octets": 42, "introuvables": 0}
    assert e["instance"]["documents_octets"] == 42
    assert e["instance"]["base_octets"] > 0                # la base reste sur le serveur


def test_stockage_indisponible(client, db, copro_a, syndic_a, token_a, monkeypatch):
    _envoyer(client, token_a, b"x" * 10)

    class Panne(stk.StockageLocal):
        def taille(self, nom):
            raise stk.StockageIndisponible("bucket injoignable")

    monkeypatch.setattr(docs, "_stockage", lambda: Panne("/nulle-part"))
    r = client.get(URL, headers=auth(token_a))
    assert r.status_code == 200
    assert "injoignable" in r.json()["erreur"] and r.json()["documents"]["octets"] is None
