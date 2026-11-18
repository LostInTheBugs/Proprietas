"""Démarrage du conteneur (issue #79) : santé pendant la migration, journal daté, puis l'application."""
import json
import logging
import urllib.error
import urllib.request

import pytest

from app import demarrage


def _get(port, chemin):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{chemin}", timeout=5) as r:
            return r.status, dict(r.headers), json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), json.loads(e.read())


def test_sante_pendant_la_migration():
    serveur = demarrage.serveur_pendant("127.0.0.1", 0)
    port = serveur.server_address[1]
    try:
        code, _, corps = _get(port, "/api/health")
        assert code == 200 and corps["status"] == "ok" and corps["phase"] == "migration"
        # /api/version ne répond pas : l'applicateur de mise à jour attend la vraie nouvelle version.
        code, entetes, corps = _get(port, "/api/version")
        assert code == 503 and entetes["Retry-After"] == "10" and "Mise à jour de la base" in corps["detail"]
        assert _get(port, "/")[0] == 503
    finally:
        serveur.shutdown()
        serveur.server_close()


def test_port_occupe_ne_bloque_pas():
    premier = demarrage.serveur_pendant("127.0.0.1", 0)
    try:
        assert demarrage.serveur_pendant("127.0.0.1", premier.server_address[1]) is None
    finally:
        premier.shutdown()
        premier.server_close()


@pytest.fixture()
def base_vide(tmp_path):
    return f"sqlite:///{tmp_path / 'copro.db'}"


def test_migration_journalisee_puis_rien_a_faire(base_vide, caplog):
    cfg = demarrage.config_alembic(base_vide)
    actuelle, cible, etapes = demarrage.revisions(cfg)
    assert actuelle is None and cible and len(etapes) > 20 and etapes[-1] == cible
    with caplog.at_level(logging.INFO):
        demarrage.migrer(cfg, periode=60)
    textes = [r.getMessage() for r in caplog.records]
    assert any(t.startswith(f"Migration de la base : révision vide → {cible}, {len(etapes)} étape(s)") for t in textes)
    assert sum(t.startswith("Étape terminée en ") for t in textes) == len(etapes)
    assert any(t.startswith("Migration terminée en ") for t in textes)
    assert demarrage.revisions(cfg) == (cible, cible, [])
    caplog.clear()
    with caplog.at_level(logging.INFO):
        demarrage.migrer(cfg, periode=60)
    assert [r.getMessage() for r in caplog.records if r.name == "proprietas.demarrage"] == \
        [f"Base à jour (révision {cible}) : aucune migration."]


def test_battement_pendant_une_longue_migration(base_vide, caplog, monkeypatch):
    from alembic import command
    attente = demarrage.threading.Event()
    monkeypatch.setattr(command, "upgrade", lambda cfg, cible: attente.wait(0.35))
    with caplog.at_level(logging.INFO):
        demarrage.migrer(demarrage.config_alembic(base_vide), periode=0.1)
    assert any(r.getMessage().startswith("Migration en cours depuis ") for r in caplog.records)


def test_description_du_blocage():
    texte = demarrage.decrire_blocage([{"pid": 4242, "app": "", "etat": "idle in transaction", "depuis": 610,
                                        "requete": "SELECT  documents.id\n  FROM documents"}])
    assert texte == "pid 4242 (sans nom, idle in transaction depuis 610 s) : SELECT documents.id FROM documents"
    assert demarrage._blocage("sqlite://") == ""            # diagnostic propre à PostgreSQL


def test_echec_de_migration_pas_de_lancement(monkeypatch):
    monkeypatch.setenv("PROPRIETAS_PORT", "0")
    lancements = []
    monkeypatch.setattr(demarrage, "migrer", lambda cfg, periode: (_ for _ in ()).throw(RuntimeError("panne")))
    assert demarrage.main(executer=lambda *a: lancements.append(a)) == 1 and lancements == []


def test_lancement_de_l_application_apres_la_migration(monkeypatch):
    monkeypatch.setenv("PROPRIETAS_PORT", "0")
    monkeypatch.setenv("PROPRIETAS_HOTE", "127.0.0.1")
    monkeypatch.setattr(demarrage, "migrer", lambda cfg, periode: None)
    lancements = []
    assert demarrage.main(executer=lambda *a: lancements.append(a)) == 0
    assert lancements == [("uvicorn", ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "0"])]
