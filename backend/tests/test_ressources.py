"""Ressources du serveur pour l'administrateur de l'instance (demande de Fred, 21/11/2026).

- processeur, mémoire, disque : vus par l'application, ou par l'applicateur de mises à jour (côté hôte, il voit
  toute la machine et le détail par conteneur : application, base de données, Jitsi…) ;
- l'applicateur écrit `ressources.json` chaque minute dans le dossier partagé ; au-delà de trois minutes, ces
  chiffres sont signalés comme anciens ;
- réservé à l'administrateur de l'instance.
"""
import json
import time

import pytest

from app.core.config import get_settings
from tests.conftest import auth


@pytest.fixture(autouse=True)
def _isoler(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "update_dir", str(tmp_path / "updates"))
    (tmp_path / "updates").mkdir()


def _admin(db, user):
    user.is_instance_admin = True
    db.commit()


def _ecrire(tmp_path, **extra):
    data = {"at": time.time(),
            "hote": {"cpus": 4, "charge": [0.5, 0.4, 0.3], "memoire": {"total": 8_000_000_000, "disponible": 6_000_000_000},
                     "disque": {"total": 100_000_000_000, "utilise": 40_000_000_000, "libre": 60_000_000_000},
                     "demarre_depuis_s": 3600},
            "services": [
                {"service": "backend", "conteneur": "proprietas-backend-1", "cpu_pct": 1.5, "mem_octets": 150_000_000,
                 "mem_limite": 8_000_000_000},
                {"service": "db", "conteneur": "proprietas-db-1", "cpu_pct": 0.2, "mem_octets": 50_000_000,
                 "mem_limite": 8_000_000_000},
                {"service": "jitsi-web", "conteneur": "proprietas-jitsi-web-1", "cpu_pct": 0.1, "mem_octets": 30_000_000,
                 "mem_limite": 8_000_000_000},
                {"service": "jitsi-jvb", "conteneur": "proprietas-jitsi-jvb-1", "cpu_pct": 3.0, "mem_octets": 300_000_000,
                 "mem_limite": 8_000_000_000},
            ]}
    data.update(extra)
    (tmp_path / "updates" / "ressources.json").write_text(json.dumps(data), encoding="utf-8")


def test_reserve_a_l_administrateur(client, db, syndic_a, token_a):
    assert client.get("/api/instance/ressources", headers=auth(token_a)).status_code == 403


def test_sans_applicateur_vue_de_l_application(client, db, syndic_a, token_a):
    _admin(db, syndic_a)
    r = client.get("/api/instance/ressources", headers=auth(token_a))
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["source"] == "application" and e["applicateur"]["present"] is False
    assert e["systeme"]["cpus"] >= 1 and e["systeme"]["disque"]["total"] > 0
    assert e["application"]["memoire_octets"] > 0                      # mémoire du processus
    assert e["services"] == []


def test_avec_applicateur_detail_par_service(client, db, syndic_a, token_a, tmp_path):
    _admin(db, syndic_a)
    _ecrire(tmp_path)
    e = client.get("/api/instance/ressources", headers=auth(token_a)).json()
    assert e["source"] == "hote" and e["applicateur"]["a_jour"] is True
    assert e["systeme"]["cpus"] == 4 and e["systeme"]["memoire"]["utilisee"] == 2_000_000_000
    groupes = {g["groupe"]: g for g in e["services"]}
    assert set(groupes) == {"Application", "Base de données", "Jitsi"}
    j = groupes["Jitsi"]
    assert j["mem_octets"] == 330_000_000 and j["cpu_pct"] == 3.1 and len(j["conteneurs"]) == 2
    # Chiffres anciens (applicateur arrêté) : signalés, la vue de l'application reprend la main.
    _ecrire(tmp_path, at=time.time() - 600)
    e = client.get("/api/instance/ressources", headers=auth(token_a)).json()
    assert e["applicateur"]["present"] is True and e["applicateur"]["a_jour"] is False
    assert e["source"] == "application" and e["services_anciens"] is True
