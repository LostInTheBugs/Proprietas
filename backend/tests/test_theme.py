"""Thème d'affichage (clair / sombre / système) — préférence par compte."""
from sqlalchemy import text

from tests.conftest import auth


def test_theme_defaut_et_mise_a_jour(client, syndic_a, token_a):
    r = client.get("/api/auth/me", headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert r.json()["theme"] == "system"

    r = client.post("/api/auth/theme", json={"theme": "dark"}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert r.json()["theme"] == "dark"

    r = client.get("/api/auth/me", headers=auth(token_a))
    assert r.json()["theme"] == "dark"


def test_theme_invalide_refuse(client, syndic_a, token_a):
    r = client.post("/api/auth/theme", json={"theme": "rainbow"}, headers=auth(token_a))
    assert r.status_code == 422


def test_theme_null_sur_ligne_existante_reste_lisible(client, db, syndic_a, token_a):
    """Régression : colonne ajoutée par ALTER TABLE = NULL sur les lignes existantes."""
    db.execute(text("UPDATE users SET theme = NULL WHERE id = :i"), {"i": syndic_a.id})
    db.commit()
    db.expire_all()
    r = client.get("/api/auth/me", headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert r.json()["theme"] == "system"
