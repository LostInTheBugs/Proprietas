"""Supervision (demande de Fred, 22/11/2026) : activité de l'API et état du serveur, relevés toutes les 5 minutes.

- `noter_requete` (middleware de app/main.py) compte chaque requête de l'API : nombre, erreurs 5xx, durée.
  /api/health (supervision externe) et les pages de l'interface ne sont pas comptées.
- `releve` (planificateur, toutes les 5 minutes) enregistre processeur, mémoire et disque (services/ressources.py :
  machine entière si l'applicateur tourne, sinon vue de l'application) avec les compteurs, puis les remet à zéro.
- Les relevés de plus de 7 jours sont supprimés.
- Après chaque relevé, services/alertes_serveur.py vérifie les seuils et prévient les administrateurs.
Un seul processus uvicorn (comme le planificateur) : les compteurs sont en mémoire.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.supervision import MesureServeur

INTERVALLE_MINUTES = 5
CONSERVATION_JOURS = 7
MAX_DUREES = 20_000           # durées gardées par intervalle (au-delà : échantillon des premières)
IGNOREES = ("/api/health",)

_verrou = threading.Lock()
_requetes = 0
_erreurs = 0
_durees: list[float] = []
# Totaux depuis le démarrage, pour GET /api/metrics (Prometheus : compteurs et histogramme des durées).
SEUILS_DUREE = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
totaux = {"requetes": 0, "erreurs": 0, "somme_durees": 0.0, "seaux": [0] * (len(SEUILS_DUREE) + 1)}


def reinitialiser() -> tuple[int, int, list[float]]:
    """Remet les compteurs à zéro ; renvoie (requêtes, erreurs 5xx, durées en secondes) de l'intervalle."""
    global _requetes, _erreurs, _durees
    with _verrou:
        r = (_requetes, _erreurs, _durees)
        _requetes, _erreurs, _durees = 0, 0, []
    return r


def noter_requete(chemin: str, statut: int, duree_s: float) -> None:
    if not chemin.startswith("/api/") or chemin in IGNOREES:
        return
    global _requetes, _erreurs
    with _verrou:
        _requetes += 1
        totaux["requetes"] += 1
        totaux["somme_durees"] += duree_s
        totaux["seaux"][next((i for i, s in enumerate(SEUILS_DUREE) if duree_s <= s), len(SEUILS_DUREE))] += 1
        if statut >= 500:
            _erreurs += 1
            totaux["erreurs"] += 1
        if len(_durees) < MAX_DUREES:
            _durees.append(duree_s)


def _p95(durees: list[float]) -> float | None:
    if not durees:
        return None
    triees = sorted(durees)
    return triees[min(len(triees) - 1, int(round(0.95 * (len(triees) - 1))))]


def _pct(utilise, total) -> float | None:
    return round(utilise / total * 100, 1) if total else None


def releve(db: Session) -> MesureServeur:
    from app.services import ressources
    etat = ressources.etat(".", None)
    s = etat["systeme"]
    charge = s.get("charge") or []
    requetes, erreurs, durees = reinitialiser()
    m = MesureServeur(
        instant=datetime.now(),
        cpu_pct=round(charge[0] / (s.get("cpus") or 1) * 100, 1) if charge else None,
        memoire_pct=_pct((s.get("memoire") or {}).get("utilisee"), (s.get("memoire") or {}).get("total")),
        disque_pct=_pct((s.get("disque") or {}).get("utilise"), (s.get("disque") or {}).get("total")),
        requetes=requetes, erreurs_5xx=erreurs,
        latence_moy_ms=round(sum(durees) / len(durees) * 1000, 1) if durees else None,
        latence_p95_ms=round(_p95(durees) * 1000, 1) if durees else None,
        source=etat["source"],
    )
    db.add(m)
    db.query(MesureServeur).filter(
        MesureServeur.instant < datetime.now() - timedelta(days=CONSERVATION_JOURS)).delete(synchronize_session=False)
    db.commit()
    db.refresh(m)
    return m


def historique(db: Session, heures: int) -> dict:
    depuis = datetime.now() - timedelta(hours=heures)
    mesures = (db.query(MesureServeur).filter(MesureServeur.instant >= depuis)
               .order_by(MesureServeur.instant).all())
    from app.services import alertes_serveur
    return {"heures": heures, "intervalle_minutes": INTERVALLE_MINUTES,
            "incidents": alertes_serveur.recents(db, heures),
            "externe": {"metrics": bool(get_settings().metrics_token), "journal": get_settings().log_format},
            "mesures": [{"instant": m.instant, "cpu_pct": m.cpu_pct, "memoire_pct": m.memoire_pct,
                         "disque_pct": m.disque_pct, "requetes": m.requetes, "erreurs_5xx": m.erreurs_5xx,
                         "latence_moy_ms": m.latence_moy_ms, "latence_p95_ms": m.latence_p95_ms,
                         "source": m.source} for m in mesures]}
