"""Supervision externe et journaux (demande de Fred, 22/11/2026).

- `GET /api/metrics` : format Prometheus, protégé par le jeton `COPRO_METRICS_TOKEN` (désactivé sans jeton : 404).
- Chaque réponse porte un identifiant de requête `X-Request-ID` (repris de la requête s'il est valide).
- `COPRO_LOG_FORMAT=json` : une ligne JSON par requête de l'API (identifiant, compte, copropriété, méthode, chemin,
  code, durée) et pour chaque message du journal, prête pour Loki ou un autre collecteur.
"""
import json
import logging
import re

import pytest

from app.core.config import get_settings
from tests.conftest import auth

JETON = "jeton-de-supervision-0123456789abcdef"


@pytest.fixture()
def jeton(monkeypatch):
    monkeypatch.setattr(get_settings(), "metrics_token", JETON, raising=False)
    return {"Authorization": f"Bearer {JETON}"}


def test_metrics_desactive_sans_jeton(client):
    assert client.get("/api/metrics").status_code == 404


def test_metrics_protege_et_au_format_prometheus(client, db, syndic_a, token_a, jeton):
    from app.services import supervision
    assert client.get("/api/metrics").status_code == 401
    assert client.get("/api/metrics", headers={"Authorization": "Bearer mauvais"}).status_code == 401
    assert client.get("/api/metrics", headers=auth(token_a)).status_code == 401     # un jeton de session ne suffit pas
    supervision.releve(db)
    avant = client.get("/api/metrics", headers=jeton)
    assert avant.status_code == 200 and avant.headers["content-type"].startswith("text/plain")
    t = avant.text
    for ligne in ('proprietas_info{version="', "# TYPE proprietas_requetes_total counter", "proprietas_erreurs_5xx_total ",
                  'proprietas_requete_duree_secondes_bucket{le="0.1"} ', 'proprietas_requete_duree_secondes_bucket{le="+Inf"} ',
                  "proprietas_requete_duree_secondes_count ", "proprietas_incidents_en_cours 0",
                  "proprietas_coproprietes ", "proprietas_disque_pct "):
        assert ligne in t, ligne
    total = lambda txt: float(re.search(r"^proprietas_requetes_total (\S+)$", txt, re.M).group(1))  # noqa: E731
    for _ in range(3):
        client.get("/api/lots", headers=auth(token_a))
    assert total(client.get("/api/metrics", headers=jeton).text) >= total(t) + 3


def test_identifiant_de_requete(client):
    r = client.get("/api/health")
    assert re.fullmatch(r"[0-9a-f]{16}", r.headers["x-request-id"])
    assert client.get("/api/health", headers={"X-Request-ID": "trace-42"}).headers["x-request-id"] == "trace-42"
    autre = client.get("/api/health", headers={"X-Request-ID": "pas\nvalide" * 20}).headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{16}", autre)


def test_journal_json_par_requete(client, db, copro_a, syndic_a, token_a, monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "log_format", "json", raising=False)
    # Un test de migration (alembic, fileConfig) a pu désactiver les journaux déjà créés : on le rallume.
    monkeypatch.setattr(logging.getLogger("proprietas.requete"), "disabled", False)
    with caplog.at_level(logging.INFO, logger="proprietas.requete"):
        r = client.get("/api/lots", headers=auth(token_a))
    rec = next(x for x in caplog.records if x.name == "proprietas.requete")
    assert (rec.methode, rec.chemin, rec.statut, rec.user_id, rec.copro_id) == \
        ("GET", "/api/lots", 200, syndic_a.id, copro_a.id)
    assert rec.request_id == r.headers["x-request-id"] and rec.duree_ms >= 0
    from app.core.journal import FormatJSON
    ligne = json.loads(FormatJSON().format(rec))
    assert ligne["logger"] == "proprietas.requete" and ligne["statut"] == 200 and ligne["user_id"] == syndic_a.id
    assert "ts" in ligne and ligne["niveau"] == "INFO"


def test_journal_texte_par_defaut_sans_ligne_par_requete(client, token_a, caplog):
    with caplog.at_level(logging.INFO, logger="proprietas.requete"):
        client.get("/api/lots", headers=auth(token_a))
    assert not [x for x in caplog.records if x.name == "proprietas.requete"]    # uvicorn trace déjà les accès


def test_format_json_des_exceptions():
    from app.core.journal import FormatJSON
    try:
        raise ValueError("boum")
    except ValueError:
        import sys
        rec = logging.LogRecord("proprietas", logging.ERROR, __file__, 1, "échec %s", ("x",), sys.exc_info())
    d = json.loads(FormatJSON().format(rec))
    assert d["message"] == "échec x" and "ValueError: boum" in d["exception"]
