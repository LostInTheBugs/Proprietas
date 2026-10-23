"""Migration des bibliothèques d'authentification : python-jose → PyJWT, passlib → bcrypt.

Deux familles de tests :
- COMPATIBILITÉ (doivent passer AVANT et APRÈS la migration) : des données RÉELLES figées,
  produites par l'ancienne pile (passlib 1.7.4 / python-jose 3.3.0), restent valides.
  Personne ne doit être déconnecté ni perdre son mot de passe.
- NOUVEAU COMPORTEMENT (échouent avant) : dépendances retirées, hash corrompu = refus propre.
"""
from pathlib import Path

import pytest

from app.core import security
from app.core.security import (create_access_token, decode_access_token, hash_password,
                               verify_password)
from tests.conftest import auth

# Produits le 23/10/2026 avec passlib 1.7.4 (CryptContext bcrypt) — NE PAS RÉGÉNÉRER.
HASH_PASSLIB = "$2b$12$nYxm1XYFrwQ0n83UjtlyKOZtuAjcNuQbcGTwkXuiZ/TmpAvWUv6Wi"      # "Mot-de-passe-2026!"
HASH_PASSLIB_LONG = "$2b$12$4Km6gz8T8qCFsltGnsXLGu2d8TGw3Pus5ZS/JYUkW63D9ZMCocTMi"  # "é" * 50 (100 octets)
# Produit avec python-jose 3.3.0, HS256, clé ci-dessous, exp = 2100-01-01 — NE PAS RÉGÉNÉRER.
CLE_FIGEE = "cle-de-test-figee-pour-la-compatibilite"
JETON_JOSE = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjo0MTAyNDQ0ODAwLCJ2ZXIiOjAs"
              "ImNvcHJvX2lkIjoxfQ.RqSNJxkIHCqKkIPDC_ephFw6cJN5MIW10kWLs4-TRUg")

REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements.txt"


# ---------------------------------------------------------------- compatibilité (avant ET après)
def test_hash_passlib_existant_toujours_valide():
    assert verify_password("Mot-de-passe-2026!", HASH_PASSLIB) is True
    assert verify_password("mauvais", HASH_PASSLIB) is False


def test_troncature_72_octets_conservee():
    # passlib tronquait à 72 octets sans erreur : un mot de passe long déjà enregistré
    # doit rester valide, et le comportement est le même pour les nouveaux hachages.
    assert verify_password("é" * 50, HASH_PASSLIB_LONG) is True
    assert verify_password("é" * 36 + "suffixe ignoré", HASH_PASSLIB_LONG) is True
    nouveau = hash_password("é" * 50)
    assert verify_password("é" * 36, nouveau) is True


def test_nouveau_hash_au_format_bcrypt_2b():
    h = hash_password("Mot-de-passe-2026!")
    assert h.startswith("$2b$12$") and len(h) == 60
    assert verify_password("Mot-de-passe-2026!", h) is True


def test_jeton_jose_existant_toujours_valide(monkeypatch):
    monkeypatch.setattr(security.settings, "secret_key", CLE_FIGEE)
    assert decode_access_token(JETON_JOSE) == {"sub": "1", "exp": 4102444800, "ver": 0, "copro_id": 1}


def test_jeton_aller_retour_et_refus(monkeypatch):
    tok = create_access_token(7, copro_id=3, ver=2)
    p = decode_access_token(tok)
    assert p["sub"] == "7" and p["copro_id"] == 3 and p["ver"] == 2
    assert decode_access_token(tok[:-2] + "xx") is None          # signature altérée
    assert decode_access_token("pas-un-jeton") is None
    monkeypatch.setattr(security.settings, "secret_key", "autre-cle")
    assert decode_access_token(tok) is None                       # mauvaise clé


def test_jeton_alg_none_refuse():
    # Attaque classique : jeton non signé (« alg: none »).
    sans_signature = ("eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiIxIiwiZXhwIjo0MTAyNDQ0ODAwfQ.")
    assert decode_access_token(sans_signature) is None


# ---------------------------------------------------------------- nouveau comportement
def test_hash_corrompu_refus_propre_et_pas_500(client, db, syndic_a):
    # Un hash illisible en base (import, saisie manuelle) : refus, pas d'exception.
    assert verify_password("x", "pas-un-hash-bcrypt") is False
    syndic_a.password_hash = "pas-un-hash-bcrypt"
    db.commit()
    r = client.post("/api/auth/login", json={"email": "syndic.a@test.fr", "password": "test1234"})
    assert r.status_code == 401, r.text


def test_dependances_auth_maintenues():
    lignes = [l.split("#")[0].strip().lower() for l in REQUIREMENTS.read_text().splitlines()]
    noms = {l.split("==")[0].split("[")[0] for l in lignes if l}
    assert "python-jose" not in noms and "passlib" not in noms
    assert {"pyjwt", "bcrypt", "cryptography"} <= noms
    assert all("==" in l for l in lignes if l.split("==")[0] in ("pyjwt", "bcrypt", "cryptography"))
    assert "pydantic[email-validator]" not in " ".join(lignes)      # extra inexistant


def test_jeton_valide_accepte_par_l_api(client, token_a):
    assert client.get("/api/auth/me", headers=auth(token_a)).status_code == 200
