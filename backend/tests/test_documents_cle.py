"""Documents et clé secrète (avis de Perplexity relayé par Fred, 21/11/2026).

- Un document envoyé doit avoir le contenu de son extension (signature des premiers octets : PDF, PNG, JPEG,
  formats Office et OpenDocument) : un exécutable renommé en .pdf est refusé.
- Le diagnostic (Réglages → Serveur) signale une clé secrète trop courte, et rappelle de garder une copie du
  `.env` : sans la même clé, les mots de passe SMTP et la double authentification enregistrés sont perdus.
"""
import pytest

from tests.conftest import auth

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 20
JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 20
ZIP = b"PK\x03\x04" + b"\0" * 20                  # .docx, .xlsx, .odt, .ods
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 20   # .doc, .xls


def _envoyer(client, token, nom, contenu):
    return client.post("/api/documents", data={"categorie": "autre", "libelle": "Pièce"},
                       files={"fichier": (nom, contenu, "application/octet-stream")}, headers=auth(token))


@pytest.mark.parametrize("nom, contenu", [
    ("facture.pdf", b"%PDF-1.7\n..."), ("photo.png", PNG), ("photo.jpg", JPEG), ("scan.JPEG", JPEG),
    ("devis.docx", ZIP), ("budget.xlsx", ZIP), ("note.odt", ZIP), ("tableau.ods", ZIP),
    ("ancien.doc", OLE), ("ancien.xls", OLE),
])
def test_contenu_conforme_accepte(client, token_a, nom, contenu):
    r = _envoyer(client, token_a, nom, contenu)
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("nom, contenu", [
    ("facture.pdf", b"MZ\x90\x00 programme Windows"),     # exécutable renommé
    ("photo.png", b"%PDF-1.7 un PDF renomme"),
    ("devis.docx", b"<html><script>alert(1)</script>"),
    ("vide.pdf", b""),
])
def test_contenu_non_conforme_refuse(client, token_a, nom, contenu):
    r = _envoyer(client, token_a, nom, contenu)
    assert r.status_code == 400, r.text
    assert "ne correspond pas" in r.json()["detail"]


def _diagnostic(client, token):
    r = client.post("/api/instance/diagnostic", headers=auth(token))
    assert r.status_code == 200, r.text
    return {i["id"]: i for i in r.json()["results"]}


def test_diagnostic_cle_secrete(client, token_a, monkeypatch):
    from app.core.config import get_settings
    cle = _diagnostic(client, token_a)["cle"]
    assert cle["statut"] == "ok" and ".env" in cle["detail"]
    assert get_settings().secret_key not in cle["detail"]                 # jamais la clé elle-même
    # Clé courte (vérifiée sans requête : changer la clé invaliderait aussi le jeton du test).
    from app.services import diagnostic
    monkeypatch.setattr(get_settings(), "secret_key", "courte")
    cle = diagnostic._check_cle()
    assert cle["statut"] == "attention" and "32" in cle["detail"] and "courte" not in cle["detail"]
