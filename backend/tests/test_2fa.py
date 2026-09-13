"""Double authentification (TOTP) : enrôlement, connexion en 2 étapes, codes de secours.

Le rate-limit du login est partagé entre l'étape mot de passe et l'étape 2FA —
les tests qui manipulent ses compteurs les nettoient avant/après (état module).
"""
import pyotp

from tests.conftest import _make_membre, auth
from app.core import rate_limit
from app.core.security import create_access_token, hash_password
from app.models.user import User, UserCopro


def _enroler(client, token):
    """Enrôle la 2FA avec le jeton donné ; renvoie (secret, codes de secours)."""
    r = client.post("/api/auth/2fa/setup", headers=auth(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["qr_svg"].startswith("data:image/svg+xml;base64,")
    assert data["otpauth_uri"].startswith("otpauth://totp/")
    code = pyotp.TOTP(data["secret"]).now()
    r = client.post("/api/auth/2fa/verify", json={"code": code}, headers=auth(token))
    assert r.status_code == 200, r.text
    return data["secret"], r.json()["recovery_codes"]


def _login(client, email, password="test1234"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_statut_initial_et_enrolement(client, db, copro_a, syndic_a, token_a):
    d = client.get("/api/auth/2fa/status", headers=auth(token_a)).json()
    assert d["enabled"] is False and d["recovery_codes_left"] == 0
    assert d["required"] is False  # politique off par défaut dans les tests

    secret, codes = _enroler(client, token_a)
    assert len(secret) >= 16
    assert len(codes) == 10 and all("-" in c for c in codes)

    d = client.get("/api/auth/2fa/status", headers=auth(token_a)).json()
    assert d["enabled"] is True and d["recovery_codes_left"] == 10


def test_login_deux_etapes_code_totp(client, db, copro_a, syndic_a, token_a):
    secret, _ = _enroler(client, token_a)
    # Étape 1 : mot de passe → jeton de challenge, PAS de jeton d'accès
    d = _login(client, "syndic.a@test.fr").json()
    assert d["two_factor_required"] is True and d["access_token"] is None
    assert d["challenge_token"]
    # Le jeton de challenge ne donne accès à rien d'autre
    assert client.get("/api/auth/me", headers=auth(d["challenge_token"])).status_code == 401
    assert client.get("/api/copro", headers=auth(d["challenge_token"])).status_code == 401
    # Mauvais code
    r = client.post("/api/auth/2fa/verify-login",
                    json={"challenge_token": d["challenge_token"], "code": "12345"})
    assert r.status_code == 401
    # Bon code → jeton complet
    r = client.post("/api/auth/2fa/verify-login",
                    json={"challenge_token": d["challenge_token"],
                          "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    assert client.get("/api/auth/me", headers=auth(tok)).status_code == 200


def test_code_secours_usage_unique(client, db, copro_a, syndic_a, token_a):
    _, codes = _enroler(client, token_a)
    d = _login(client, "syndic.a@test.fr").json()
    r = client.post("/api/auth/2fa/verify-login",
                    json={"challenge_token": d["challenge_token"], "code": codes[0]})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    assert client.get("/api/auth/2fa/status", headers=auth(tok)).json()["recovery_codes_left"] == 9

    # Le même code ne peut pas resservir
    d = _login(client, "syndic.a@test.fr").json()
    r = client.post("/api/auth/2fa/verify-login",
                    json={"challenge_token": d["challenge_token"], "code": codes[0]})
    assert r.status_code == 401

    # Insensible à la casse / espaces / tirets
    d = _login(client, "syndic.a@test.fr").json()
    r = client.post("/api/auth/2fa/verify-login",
                    json={"challenge_token": d["challenge_token"],
                          "code": codes[1].lower().replace("-", " ")})
    assert r.status_code == 200, r.text


def test_desactivation_exige_mdp_et_code(client, db, copro_a, syndic_a, token_a):
    secret, _ = _enroler(client, token_a)
    r = client.post("/api/auth/2fa/disable", json={"password": "mauvais", "code": pyotp.TOTP(secret).now()},
                    headers=auth(token_a))
    assert r.status_code == 400
    r = client.post("/api/auth/2fa/disable", json={"password": "test1234", "code": "ABC123"},
                    headers=auth(token_a))
    assert r.status_code == 400
    r = client.post("/api/auth/2fa/disable",
                    json={"password": "test1234", "code": pyotp.TOTP(secret).now()},
                    headers=auth(token_a))
    assert r.status_code == 200
    # Connexion directe, sans étape 2FA
    d = _login(client, "syndic.a@test.fr").json()
    assert d["access_token"] and not d["two_factor_required"]


def test_politique_syndic_puis_all(client, db, copro_a, syndic_a):
    _make_membre(db, "membre.a@test.fr", copro_a)
    # « syndic » : le syndic doit s'enrôler, les membres non
    copro_a.totp_policy = "syndic"
    db.commit()
    d = _login(client, "syndic.a@test.fr").json()
    assert d["must_enroll_2fa"] is True and d["challenge_token"]
    assert _login(client, "membre.a@test.fr").json()["access_token"]
    # Le statut du syndic indique l'exigence
    tok = create_access_token(syndic_a.id, copro_a.id)
    st = client.get("/api/auth/2fa/status", headers=auth(tok)).json()
    assert st["required"] is True and st["policy"] == "syndic"
    # « all » : tout le monde
    copro_a.totp_policy = "all"
    db.commit()
    assert _login(client, "membre.a@test.fr").json()["must_enroll_2fa"] is True


def test_enrolement_force_flux_complet(client, db, copro_a, syndic_a):
    copro_a.totp_policy = "syndic"
    db.commit()
    d = _login(client, "syndic.a@test.fr").json()
    assert d["must_enroll_2fa"] is True
    setup_token = d["challenge_token"]
    # Le jeton d'enrôlement ne donne accès qu'aux routes 2FA
    assert client.get("/api/copro", headers=auth(setup_token)).status_code == 401
    assert client.get("/api/audit", headers=auth(setup_token)).status_code == 401
    # Enrôlement → jeton complet délivré par la route verify
    r = client.post("/api/auth/2fa/setup", headers=auth(setup_token))
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    r = client.post("/api/auth/2fa/verify", json={"code": pyotp.TOTP(secret).now()},
                    headers=auth(setup_token))
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["recovery_codes"]) == 10
    tok = d["access_token"]
    assert tok and client.get("/api/auth/me", headers=auth(tok)).status_code == 200
    # La connexion suivante exige désormais le code
    assert _login(client, "syndic.a@test.fr").json()["two_factor_required"] is True


def test_compte_demo_exempte(client, db, copro_a):
    demo = User(email="demo@test.fr", password_hash=hash_password("demo1234"),
                nom="Demo", role="syndic", is_demo=True, copropriete_id=copro_a.id)
    db.add(demo)
    db.commit()
    db.refresh(demo)
    db.add(UserCopro(user_id=demo.id, copropriete_id=copro_a.id, principale=True))
    db.commit()
    copro_a.totp_policy = "all"
    db.commit()
    d = _login(client, "demo@test.fr", "demo1234").json()
    assert d["access_token"] and not d["must_enroll_2fa"]
    # L'enrôlement 2FA est refusé pour un compte démo
    r = client.post("/api/auth/2fa/setup", headers=auth(d["access_token"]))
    assert r.status_code == 400


def test_reset_2fa_par_syndic_et_isolation(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b):
    membre = _make_membre(db, "membre.a@test.fr", copro_a)
    _enroler(client, create_access_token(membre.id, copro_a.id))
    # Un syndic d'une AUTRE copro ne voit pas ce compte
    assert client.post(f"/api/auth/users/{membre.id}/2fa/reset",
                       headers=auth(token_b)).status_code == 404
    # Le syndic de la copro peut réinitialiser
    assert client.post(f"/api/auth/users/{membre.id}/2fa/reset",
                       headers=auth(token_a)).status_code == 200
    # Auto-réinitialisation interdite (utiliser « Désactiver »)
    assert client.post(f"/api/auth/users/{syndic_a.id}/2fa/reset",
                       headers=auth(token_a)).status_code == 400
    # Le membre se reconnecte sans 2FA et peut se ré-enrôler
    assert _login(client, "membre.a@test.fr").json()["access_token"]


def test_regeneration_codes_secours(client, db, copro_a, syndic_a, token_a):
    secret, codes = _enroler(client, token_a)
    r = client.post("/api/auth/2fa/recovery-codes",
                    json={"password": "test1234", "code": pyotp.TOTP(secret).now()},
                    headers=auth(token_a))
    assert r.status_code == 200, r.text
    nouveaux = r.json()["recovery_codes"]
    assert len(nouveaux) == 10
    assert set(nouveaux).isdisjoint(set(codes))  # les anciens sont invalidés


def test_rate_limit_2fa_partage_avec_le_login(client, db, copro_a, syndic_a, token_a):
    rate_limit._failures.clear()
    try:
        secret, _ = _enroler(client, token_a)
        challenge = _login(client, "syndic.a@test.fr").json()["challenge_token"]
        for _ in range(5):
            r = client.post("/api/auth/2fa/verify-login",
                            json={"challenge_token": challenge, "code": "12345"})
            assert r.status_code == 401
        # 6e essai, même avec le bon code → 429
        r = client.post("/api/auth/2fa/verify-login",
                        json={"challenge_token": challenge, "code": pyotp.TOTP(secret).now()})
        assert r.status_code == 429
        assert "Trop de tentatives" in r.text
    finally:
        rate_limit._failures.clear()
