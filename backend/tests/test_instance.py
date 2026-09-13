"""Profil d'exposition : détection externe, mode/URL, diagnostic, en-têtes de sécurité."""
from app.core.security import create_access_token
from tests.conftest import _make_membre, auth


def test_entetes_securite_sur_toutes_les_reponses(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    csp = r.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp


def test_pas_de_csp_sur_docs(client):
    r = client.get("/docs")
    assert r.status_code == 200
    assert "content-security-policy" not in r.headers


def test_instance_reservee_au_syndic(client, db, copro_a, syndic_a, token_a):
    assert client.get("/api/instance", headers=auth(token_a)).status_code == 200
    membre = _make_membre(db, "membre.a@test.fr", copro_a)
    r = client.get("/api/instance", headers=auth(create_access_token(membre.id, copro_a.id)))
    assert r.status_code == 403


def test_instance_defauts(client, db, copro_a, syndic_a, token_a):
    d = client.get("/api/instance", headers=auth(token_a)).json()
    assert d["mode"] == "local" and d["public_url"] == ""
    assert d["exposed_unprotected"] is False
    assert d["first_external_at"] is None
    assert d["version"]  # version de l'application


def test_instance_maj_et_validation(client, db, copro_a, syndic_a, token_a):
    r = client.put("/api/instance",
                   json={"mode": "vps", "public_url": "https://copro.exemple.fr/"},
                   headers=auth(token_a))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["mode"] == "vps" and d["public_url"] == "https://copro.exemple.fr"  # / final retiré
    # mode invalide / URL invalide → 422
    assert client.put("/api/instance", json={"mode": "xx", "public_url": ""},
                      headers=auth(token_a)).status_code == 422
    assert client.put("/api/instance", json={"mode": "local", "public_url": "ftp://x"},
                      headers=auth(token_a)).status_code == 422


def test_detection_premiere_requete_externe(client, db, copro_a, syndic_a, token_a):
    # Requête « depuis internet » : IP publique dans CF-Connecting-IP
    r = client.get("/api/health", headers={"cf-connecting-ip": "93.184.216.34"})
    assert r.status_code == 200
    d = client.get("/api/instance", headers=auth(token_a)).json()
    assert d["first_external_at"] is not None
    assert d["exposed_unprotected"] is True  # mode « local » + exposition détectée


def test_detection_ignoree_en_interne(client, db, copro_a, syndic_a, token_a):
    client.get("/api/health", headers={"cf-connecting-ip": "192.168.1.10"})
    d = client.get("/api/instance", headers=auth(token_a)).json()
    assert d["first_external_at"] is None


def test_diagnostic_avec_checks_mockes(client, db, copro_a, syndic_a, token_a, monkeypatch):
    from app.services import diagnostic

    def faux_fetch(url, timeout=10):
        if "/api/health" in url:
            return (200,
                    {"x-content-type-options": "nosniff",
                     "content-security-policy": "default-src 'self'",
                     "server": "cloudflare"},
                    b'{"status":"ok","app":"Proprietas"}')
        return (200, {}, b"")
    monkeypatch.setattr(diagnostic, "_fetch", faux_fetch)
    monkeypatch.setattr(diagnostic, "_ip_publique", lambda: "93.184.216.34")
    monkeypatch.setattr(diagnostic, "_jours_certificat", lambda host: 80)
    monkeypatch.setattr(diagnostic, "_test_rate_limit", lambda url: (True, "limiteur actif"))
    monkeypatch.setattr(diagnostic.socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])

    client.put("/api/instance", json={"mode": "vps", "public_url": "https://copro.exemple.fr"},
               headers=auth(token_a))
    r = client.post("/api/instance/diagnostic", headers=auth(token_a))
    assert r.status_code == 200, r.text
    d = r.json()
    par_id = {i["id"]: i for i in d["results"]}
    assert par_id["https"]["statut"] == "ok"
    assert par_id["cert"]["statut"] == "ok"
    assert par_id["dns"]["statut"] == "ok"
    assert par_id["headers"]["statut"] == "ok"
    assert par_id["ratelimit"]["statut"] == "ok"
    assert par_id["2fa"]["statut"] == "attention"  # politique off par défaut en test
    # Résultat persisté : le statut le renvoie
    st = client.get("/api/instance", headers=auth(token_a)).json()
    assert st["last_check_at"] is not None
    assert len(st["last_check"]) == len(d["results"])


def test_diagnostic_sans_url(client, db, copro_a, syndic_a, token_a):
    r = client.post("/api/instance/diagnostic", headers=auth(token_a))
    assert r.status_code == 200
    par_id = {i["id"]: i for i in r.json()["results"]}
    assert par_id["url"]["statut"] == "echec"
    assert par_id["https"]["statut"] == "ignore"
