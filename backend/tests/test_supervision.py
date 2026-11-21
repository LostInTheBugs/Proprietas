"""Supervision : historique des ressources et de l'activité (demande de Fred, 22/11/2026).

- chaque requête de l'API est comptée (nombre, erreurs serveur 5xx, durée) ;
- toutes les 5 minutes, un relevé est enregistré : processeur, mémoire, disque (vus de la machine si
  l'applicateur tourne, sinon de l'application), requêtes, erreurs 5xx, temps de réponse moyen et 95e centile ;
- les relevés de plus de 7 jours sont supprimés ;
- Réglages → Serveur, page « État du serveur » : historique sur 24 h ou 7 jours (administrateur seulement).
"""
from datetime import datetime, timedelta

from tests.conftest import auth


def _admin(db, user):
    user.is_instance_admin = True
    db.commit()


def test_compteurs_et_releve(client, db, syndic_a, token_a):
    from app.models.supervision import MesureServeur
    from app.services import supervision
    supervision.reinitialiser()
    for _ in range(3):
        assert client.get("/api/lots", headers=auth(token_a)).status_code == 200
    client.get("/api/health")                              # supervision externe : pas comptée
    client.get("/")                                        # pages de l'interface : pas comptées
    for duree in (0.010, 0.020, 0.030, 0.040, 2.0):
        supervision.noter_requete("/api/x", 500, duree)
    m = supervision.releve(db)
    assert m.requetes == 8 and m.erreurs_5xx == 5
    assert m.latence_p95_ms >= 2000 * 0.9 and 0 < m.latence_moy_ms < 2000
    assert 0 <= m.cpu_pct and 0 < m.memoire_pct <= 100 and 0 < m.disque_pct <= 100
    assert m.source in ("hote", "application")
    assert db.query(MesureServeur).count() == 1
    # Les compteurs repartent de zéro après chaque relevé.
    m2 = supervision.releve(db)
    assert (m2.requetes, m2.erreurs_5xx, m2.latence_p95_ms) == (0, 0, None)


def test_purge_au_dela_de_7_jours(db):
    from app.models.supervision import MesureServeur
    from app.services import supervision
    vieux = datetime.now() - timedelta(days=8)
    db.add(MesureServeur(instant=vieux, cpu_pct=1, memoire_pct=1, disque_pct=1, requetes=0, erreurs_5xx=0,
                         source="application"))
    db.commit()
    supervision.releve(db)
    assert db.query(MesureServeur).filter(MesureServeur.instant < datetime.now() - timedelta(days=7)).count() == 0
    assert db.query(MesureServeur).count() == 1


def test_historique_pour_l_administrateur(client, db, syndic_a, token_a):
    from app.models.supervision import MesureServeur
    assert client.get("/api/instance/supervision", headers=auth(token_a)).status_code == 403
    _admin(db, syndic_a)
    maintenant = datetime.now()
    for h in (60, 30, 2):                                  # il y a 60 h, 30 h et 2 h
        db.add(MesureServeur(instant=maintenant - timedelta(hours=h), cpu_pct=h, memoire_pct=50, disque_pct=40,
                             requetes=10, erreurs_5xx=1, latence_moy_ms=12.5, latence_p95_ms=40, source="hote"))
    db.commit()
    r = client.get("/api/instance/supervision?heures=24", headers=auth(token_a))
    assert r.status_code == 200, r.text
    d = r.json()
    assert [p["cpu_pct"] for p in d["mesures"]] == [2]
    assert d["intervalle_minutes"] == 5 and d["heures"] == 24
    d = client.get("/api/instance/supervision?heures=168", headers=auth(token_a)).json()
    assert [p["cpu_pct"] for p in d["mesures"]] == [60, 30, 2]           # ordre chronologique
    assert client.get("/api/instance/supervision?heures=500", headers=auth(token_a)).status_code == 422


def test_releve_planifie():
    from app.core import scheduler
    scheduler.start_scheduler()
    try:
        job = scheduler._scheduler.get_job("supervision")
        assert job is not None and job.trigger.interval == timedelta(minutes=5)
    finally:
        scheduler.stop_scheduler()
