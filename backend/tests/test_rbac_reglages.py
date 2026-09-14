"""Permissions par rôle : un copropriétaire (membre) ne peut PAS modifier les réglages.

Le frontend masque ces écrans, mais l'API reste la ligne de défense : ces tests
verrouillent les 403 (une régression = fuite de privilèges syndic → copropriétaire).
"""
from app.core.security import create_access_token
from tests.conftest import auth, _make_membre


def _token_membre(db, copro, email="membre.reglages@test.fr"):
    membre = _make_membre(db, email, copro)
    return create_access_token(membre.id, copro.id), membre


def test_membre_ne_peut_pas_modifier_la_copropriete(client, db, copro_a, token_a):
    token, _ = _token_membre(db, copro_a)
    r = client.put("/api/copro", headers=auth(token), json={"nom": "Détournement"})
    assert r.status_code == 403, r.text
    # Le syndic, lui, peut (sanity de la route).
    r = client.put("/api/copro", headers=auth(token_a), json={"nom": "Les Tilleuls"})
    assert r.status_code == 200, r.text


def test_membre_ne_peut_pas_toucher_au_smtp(client, db, copro_a):
    token, _ = _token_membre(db, copro_a)
    r = client.put("/api/smtp/config", headers=auth(token),
                   json={"smtp_host": "smtp.pirate.fr", "smtp_port": 25})
    assert r.status_code == 403, r.text
    r = client.post("/api/smtp/test", headers=auth(token),
                    json={"smtp_host": "smtp.pirate.fr", "smtp_port": 25})
    assert r.status_code == 403, r.text


def test_membre_ne_peut_pas_toucher_a_l_instance_ni_diagnostic(client, db, copro_a):
    token, _ = _token_membre(db, copro_a)
    assert client.get("/api/instance", headers=auth(token)).status_code == 403
    assert client.put("/api/instance", headers=auth(token),
                      json={"mode": "vps", "public_url": "https://pirate.fr"}).status_code == 403
    assert client.post("/api/instance/diagnostic", headers=auth(token)).status_code == 403


def test_membre_ne_peut_pas_gerer_les_comptes_ni_les_donnees(client, db, copro_a, token_a):
    token, membre = _token_membre(db, copro_a)
    # Comptes utilisateurs
    assert client.get("/api/auth/users", headers=auth(token)).status_code == 403
    assert client.post("/api/auth/users", headers=auth(token),
                       json={"email": "x@test.fr", "nom": "X", "prenom": "X",
                             "role": "syndic", "password": "motdepasse"}).status_code == 403
    assert client.delete(f"/api/auth/users/{membre.id}", headers=auth(token)).status_code == 403
    # Recouvrement (page entièrement syndic) — relances et actes compris
    assert client.get("/api/recouvrement", headers=auth(token)).status_code == 403
    assert client.post("/api/relances/envoyer", headers=auth(token), json={}).status_code == 403
    # Données de structure
    assert client.post("/api/lots", headers=auth(token),
                       json={"numero": "9", "designation": "Lot pirate", "tantiemes": 10}).status_code == 403
    # Le syndic conserve l'accès (sanity)
    assert client.get("/api/auth/users", headers=auth(token_a)).status_code == 200


def test_membre_peut_consulter(client, db, copro_a, token_a):
    """Consultation : ce que le copropriétaire DOIT garder (situation, AG, documents)."""
    token, _ = _token_membre(db, copro_a)
    assert client.get("/api/lots", headers=auth(token)).status_code == 200
    assert client.get("/api/auth/me", headers=auth(token)).status_code == 200
    assert client.get("/api/ag", headers=auth(token)).status_code == 200
    assert client.get("/api/recap", headers=auth(token)).status_code == 200
    assert client.get("/api/copro", headers=auth(token)).status_code == 200
    assert client.get("/api/consolide", headers=auth(token)).status_code == 200
