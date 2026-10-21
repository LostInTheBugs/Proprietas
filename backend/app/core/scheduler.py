"""Planificateur de tâches de fond (APScheduler, 1 seul process uvicorn)."""
import logging
import random
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.database import SessionLocal
from app.services.relance_auto import run_relances_auto
from app.services.rappels_ag import run_rappels_ag

log = logging.getLogger("uvicorn.error")

_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="Europe/Paris")
    _scheduler.add_job(
        _tick_relances,
        IntervalTrigger(minutes=30, start_date=None),
        id="relances_auto",
        max_instances=1,
        coalesce=True,
    )
    # Vérification des mises à jour : toutes les 10 min, la cadence réelle (1 h par défaut)
    # est gérée par updates.tick(). Premier passage décalé de 1 à 5 min (jitter) : le
    # démarrage n'attend jamais GitHub, et plusieurs instances ne l'interrogent pas ensemble.
    _scheduler.add_job(
        _tick_updates,
        IntervalTrigger(minutes=10,
                        start_date=datetime.now() + timedelta(seconds=random.randint(60, 300))),
        id="updates",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    log.info("Scheduler démarré (relances auto toutes les 30 min)")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("Scheduler arrêté")


def _tick_relances() -> None:
    db = SessionLocal()
    try:
        stats = run_relances_auto(db)
        if stats["copros"] > 0 or stats["envoyes"] > 0:
            log.info("Relances auto : %s", stats)
        stats_ag = run_rappels_ag(db)
        if stats_ag["ag_rappel"] > 0:
            log.info("Rappels AG : %s", stats_ag)
    except Exception:
        log.exception("Erreur pendant les tâches automatiques")
    finally:
        db.close()


def _tick_updates() -> None:
    from app.services.updates import tick
    try:
        tick()
    except Exception:
        log.exception("Erreur pendant la vérification des mises à jour")
