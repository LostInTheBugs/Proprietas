"""Mises à jour : comparaison de versions, vérification GitHub (ETag, erreurs),
droits (admin d'instance uniquement), demande d'application et mode bureau."""
import pytest

from app.core.config import get_settings
from app.services import updates
from tests.conftest import auth

REL = [
    {"tag_name": "2026.10.003", "draft": False, "prerelease": False, "published_at": "2026-10-25",
     "html_url": "https://x/3", "body": "## 2026.10.003\n- correctif PV"},
    {"tag_name": "2026.10.002", "draft": False, "prerelease": False, "published_at": "2026-10-22",
     "html_url": "https://x/2", "body": "## 2026.10.002\n- nouveauté"},
    {"tag_name": "2026.10.001", "draft": False, "prerelease": False, "published_at": "2026-10-20",
     "html_url": "https://x/1", "body": "## 2026.10.001"},
    {"tag_name": "2026.10.004", "draft": True, "prerelease": False, "body": "brouillon"},
    {"tag_name": "v1.2.0", "draft": False, "prerelease": False, "body": "format non conforme"},
]


@pytest.fixture(autouse=True)
def _isoler(tmp_path, monkeypatch):
    """Dossier partagé jetable, version installée fixée, admin d'instance = syndic A."""
    s = get_settings()
    monkeypatch.setattr(s, "update_dir", str(tmp_path / "updates"))
    monkeypatch.setattr(s, "update_mode", "server")
    monkeypatch.setattr(updates, "VERSION", "2026.10.001")


def _github(monkeypatch, code=200, data=REL, etag='"abc"', exc=None):
    appels = []

    def fake(prev_etag=""):
        appels.append(prev_etag)
        if exc:
            raise exc
        return code, data, etag
    monkeypatch.setattr(updates, "_fetch_releases", fake)
    return appels


def test_vtuple_ordonne_versions_et_correctifs():
    assert updates.vtuple("2026.10.002") > updates.vtuple("2026.10.001-c5")
    assert updates.vtuple("2026.10.001-c2") > updates.vtuple("2026.10.001")
    assert updates.vtuple("2026.11.001") > updates.vtuple("2026.10.999")


def test_check_liste_les_changements_et_ignore_brouillons(monkeypatch):
    _github(monkeypatch)
    st = updates.run_check()
    assert st["available"] is True
    assert st["latest"]["version"] == "2026.10.003"
    assert [c["version"] for c in st["changes"]] == ["2026.10.003", "2026.10.002"]
    assert "correctif PV" in st["changes"][0]["notes"]
    assert st["check"]["error"] == ""


def test_check_304_reutilise_le_cache_et_envoie_l_etag(monkeypatch):
    _github(monkeypatch)
    updates.run_check()
    appels = _github(monkeypatch, code=304, data=[])
    st = updates.run_check()
    assert appels == ['"abc"']                       # If-None-Match envoyé
    assert st["latest"]["version"] == "2026.10.003"  # cache conservé


def test_check_erreur_reseau_notee_sans_planter(monkeypatch):
    _github(monkeypatch, exc=OSError("réseau indisponible"))
    st = updates.run_check()
    assert "réseau indisponible" in st["check"]["error"]
    assert st["available"] is False


@pytest.fixture(autouse=True)
def _admin_a(db, syndic_a):
    """Le syndic A est administrateur de l'instance (case cochée dans l'application)."""
    syndic_a.is_instance_admin = True
    db.commit()


def test_routes_reservees_a_l_admin_d_instance(client, token_a, token_b):
    assert client.get("/api/admin/updates", headers=auth(token_b)).status_code == 403
    assert client.get("/api/admin/updates", headers=auth(token_a)).status_code == 200
    assert client.get("/api/updates/me", headers=auth(token_a)).json() == {"instance_admin": True}
    assert client.get("/api/updates/me", headers=auth(token_b)).json() == {"instance_admin": False}


def test_version_publique(client):
    r = client.get("/api/version")
    assert r.status_code == 200 and "version" in r.json()


def test_appliquer_depose_une_demande_unique(client, token_a, monkeypatch):
    _github(monkeypatch)
    client.post("/api/admin/updates/check", headers=auth(token_a))
    r = client.post("/api/admin/updates/apply", headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert r.json()["request"]["version"] == "2026.10.003"
    assert r.json()["request"]["by"] == "syndic.a@test.fr"
    assert client.post("/api/admin/updates/apply", headers=auth(token_a)).status_code == 409
    r = client.delete("/api/admin/updates/request", headers=auth(token_a))
    assert r.json()["request"] is None


def test_appliquer_refuse_si_deja_a_jour(client, token_a, monkeypatch):
    _github(monkeypatch, data=[REL[2]])
    client.post("/api/admin/updates/check", headers=auth(token_a))
    assert client.post("/api/admin/updates/apply", headers=auth(token_a)).status_code == 400


def test_mode_bureau_notifie_mais_n_applique_pas(client, token_a, monkeypatch):
    monkeypatch.setattr(get_settings(), "update_mode", "desktop")
    _github(monkeypatch)
    st = client.post("/api/admin/updates/check", headers=auth(token_a)).json()
    assert st["available"] is True
    assert client.post("/api/admin/updates/apply", headers=auth(token_a)).status_code == 400


def test_reglages_valides_et_bornes(client, token_a):
    r = client.put("/api/admin/updates/settings", headers=auth(token_a),
                   json={"check_interval_s": 21600, "auto_apply": True})
    assert r.json()["settings"] == {"check_interval_s": 21600, "auto_apply": True}
    r = client.put("/api/admin/updates/settings", headers=auth(token_a), json={"check_interval_s": 60})
    assert r.status_code == 400


def test_tick_auto_apply_depose_la_demande(monkeypatch):
    _github(monkeypatch)
    updates.write_settings({"auto_apply": True})
    updates.tick()
    assert updates.state()["request"]["version"] == "2026.10.003"


def test_tick_sans_auto_apply_ne_demande_rien(monkeypatch):
    _github(monkeypatch)
    updates.tick()
    st = updates.state()
    assert st["available"] is True and st["request"] is None


def test_bureau_le_syndic_local_est_admin(client, token_a, token_b, monkeypatch):
    monkeypatch.setattr(get_settings(), "update_mode", "desktop")
    assert client.get("/api/updates/me", headers=auth(token_b)).json() == {"instance_admin": True}
