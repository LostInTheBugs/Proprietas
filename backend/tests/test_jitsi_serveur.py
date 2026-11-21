"""Serveur Jitsi propre, en option (demande de Fred, 21/11/2026).

- réglage de la copropriété « serveur Jitsi » : vide = celui de l'instance (COPRO_JITSI_URL, meet.jit.si par défaut) ;
- les salles créées par l'application le sont sur ce serveur ;
- docker-compose.yml : serveur Jitsi prêt à lancer, profil « jitsi », éteint par défaut.
"""
from pathlib import Path

import pytest

from tests.conftest import auth
from tests.test_ag_presences import _ag

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def test_reglage_du_serveur_jitsi(client, db, copro_a, syndic_a, token_a, token_b):
    ag_id = _ag(client, token_a)
    assert client.get("/api/copro", headers=auth(token_a)).json()["jitsi_url"] == ""
    for mauvais in ("http://visio.exemple.fr", "visio.exemple.fr", "https://visio exemple.fr"):
        assert client.put("/api/copro", json={"jitsi_url": mauvais}, headers=auth(token_a)).status_code == 422, mauvais
    r = client.put("/api/copro", json={"jitsi_url": " https://visio.exemple.fr/ "}, headers=auth(token_a))
    assert r.status_code == 200 and r.json()["jitsi_url"] == "https://visio.exemple.fr"
    lien = client.post(f"/api/ag/{ag_id}/lien-jitsi", headers=auth(token_a)).json()["lien_visio"]
    assert lien.startswith("https://visio.exemple.fr/Proprietas-")
    # Une autre copropriété garde le serveur de l'instance.
    ag_b = _ag(client, token_b)
    assert client.post(f"/api/ag/{ag_b}/lien-jitsi", headers=auth(token_b)).json()["lien_visio"].startswith(
        "https://meet.jit.si/Proprietas-")
    # Réglage vidé : retour au serveur de l'instance.
    client.put("/api/copro", json={"jitsi_url": ""}, headers=auth(token_a))
    assert client.post(f"/api/ag/{ag_id}/lien-jitsi", headers=auth(token_a)).json()["lien_visio"].startswith(
        "https://meet.jit.si/")


def _compose() -> dict:
    yaml = pytest.importorskip("yaml")
    if not COMPOSE.exists():
        pytest.skip("docker-compose.yml absent (image Docker)")
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_compose_jitsi_en_option():
    services = _compose()["services"]
    jitsi = {n: s for n, s in services.items() if n.startswith("jitsi-")}
    assert set(jitsi) == {"jitsi-web", "jitsi-prosody", "jitsi-jicofo", "jitsi-jvb"}
    for nom, s in jitsi.items():
        assert s.get("profiles") == ["jitsi"], nom                         # éteint par défaut
        assert s["image"].startswith("jitsi/"), nom
    for nom in ("db", "backend"):
        assert "profiles" not in services[nom]                               # l'application ne dépend pas de Jitsi
        assert not any(d.startswith("jitsi") for d in services[nom].get("depends_on", {}))
    assert any("/udp" in str(p) for p in jitsi["jitsi-jvb"]["ports"])        # flux audio et vidéo
    env = jitsi["jitsi-prosody"]["environment"]
    assert "JICOFO_AUTH_PASSWORD" in env and "JVB_AUTH_PASSWORD" in env
