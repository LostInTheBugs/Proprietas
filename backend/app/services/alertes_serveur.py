"""Alertes de supervision par e-mail aux administrateurs de l'instance (demande de Fred, 22/11/2026).

Appelé après chaque relevé (services/supervision.py, toutes les 5 minutes). Problèmes surveillés :
- disque à 90 % ou plus (dernier relevé) ;
- mémoire à 95 % ou plus sur les 3 derniers relevés, processeur à 90 % ou plus en moyenne sur ces 3 relevés
  (15 minutes : un pic passager ne déclenche rien) ;
- 10 erreurs serveur (5xx) ou plus en 5 minutes ;
- applicateur des mises à jour installé mais muet depuis plus de 15 minutes ;
- sauvegarde automatique sur le drive en échec dans une copropriété.
Un problème ouvre un incident et envoie un e-mail ; tant qu'il dure, un rappel au plus toutes les 24 h ; quand il
disparaît, l'incident est fermé et un e-mail « résolu » part. Les envois ne bloquent jamais : sans
administrateur ni serveur d'envoi, l'incident est seulement noté (visible dans « État du serveur »).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.copropriete import Copropriete
from app.models.supervision import Incident, MesureServeur
from app.models.user import User

log = logging.getLogger("uvicorn.error")

SEUIL_DISQUE = 90
SEUIL_MEMOIRE = 95
SEUIL_CPU = 90
SEUIL_ERREURS = 10
APPLICATEUR_MUET_S = 15 * 60
RAPPEL = timedelta(hours=24)
CONSERVATION = timedelta(days=30)
LIBELLES = {"disque": "Disque presque plein", "memoire": "Mémoire saturée", "cpu": "Processeur surchargé",
            "erreurs": "Erreurs serveur à répétition", "applicateur": "Applicateur des mises à jour arrêté",
            "sauvegarde": "Sauvegarde automatique en échec"}


def _pct(v) -> str:
    return f"{v:.1f}".replace(".", ",") + " %"


def _problemes(db: Session) -> dict[str, str]:
    """{code: détail} des problèmes présents maintenant."""
    out: dict[str, str] = {}
    derniers = db.query(MesureServeur).order_by(MesureServeur.instant.desc()).limit(3).all()
    if derniers:
        m = derniers[0]
        if m.disque_pct is not None and m.disque_pct >= SEUIL_DISQUE:
            out["disque"] = f"Disque utilisé à {_pct(m.disque_pct)} (seuil : {SEUIL_DISQUE} %)."
        if (m.erreurs_5xx or 0) >= SEUIL_ERREURS:
            out["erreurs"] = (f"{m.erreurs_5xx} erreurs serveur (5xx) en 5 minutes, sur {m.requetes} requêtes. "
                              "Voyez le journal de l'application (docker compose logs backend).")
        recents = [x for x in derniers if x.instant >= datetime.now() - timedelta(minutes=20)]
        if len(recents) == 3:
            mem = [x.memoire_pct for x in recents]
            if all(v is not None and v >= SEUIL_MEMOIRE for v in mem):
                out["memoire"] = f"Mémoire utilisée à {_pct(min(mem))} ou plus depuis 15 minutes (seuil : {SEUIL_MEMOIRE} %)."
            cpu = [x.cpu_pct for x in recents]
            if all(v is not None for v in cpu) and sum(cpu) / 3 >= SEUIL_CPU:
                out["cpu"] = f"Processeur occupé à {_pct(sum(cpu) / 3)} en moyenne sur 15 minutes (seuil : {SEUIL_CPU} %)."
    try:
        statut = json.loads((Path(get_settings().update_dir) / "update-applier.json").read_text(encoding="utf-8"))
        vu = float(statut.get("seen_at") or 0)
        if vu and time.time() - vu > APPLICATEUR_MUET_S:
            out["applicateur"] = (f"L'applicateur des mises à jour ne s'est pas manifesté depuis "
                                  f"{int((time.time() - vu) // 60)} minutes (minuterie proprietas-update.timer). "
                                  "Les mises à jour et le relevé des ressources sont arrêtés.")
    except (OSError, ValueError, TypeError):
        pass
    echecs = db.query(Copropriete).filter(Copropriete.drive_sauvegarde_erreur.isnot(None),
                                          Copropriete.drive_sauvegarde_erreur != "").all()
    if echecs:
        out["sauvegarde"] = "Sauvegarde automatique sur le drive en échec : " + " ; ".join(
            f"{c.nom} ({c.drive_sauvegarde_erreur})" for c in echecs) + "."
    return out


def _destinataires(db: Session) -> list[tuple[User, Copropriete]]:
    from app.services.alertes import _copro_smtp
    out = []
    for u in db.query(User).filter(User.is_instance_admin.is_(True), User.is_demo.isnot(True)).all():
        copro = _copro_smtp(db, u)
        if copro is not None and u.email:
            out.append((u, copro))
    return out


def _envoyer(db: Session, sujet: str, corps: str) -> bool:
    from app.services import emailer
    envoye = False
    for u, copro in _destinataires(db):
        try:
            emailer.envoyer_email(copro, u.email, sujet, f"Bonjour {u.prenom or u.nom or ''},\n\n{corps}\n\n"
                                  "Détail : Réglages → Serveur → État du serveur.\n\n— Proprietas (supervision)")
            envoye = True
        except Exception as e:  # noqa: BLE001 — une alerte ne doit jamais faire échouer la supervision
            log.warning("Alerte de supervision non envoyée à %s : %s", u.email, e)
    return envoye


def verifier(db: Session) -> dict[str, list[str]]:
    """Ouvre, rappelle ou ferme les incidents ; renvoie {ouverts, rappels, resolus} (codes)."""
    maintenant = datetime.now()
    presents = _problemes(db)
    ouverts = {i.code: i for i in db.query(Incident).filter(Incident.fin.is_(None))}
    bilan: dict[str, list[str]] = {"ouverts": [], "rappels": [], "resolus": []}
    for code, detail in presents.items():
        inc = ouverts.get(code)
        if inc is None:
            inc = Incident(code=code, debut=maintenant, detail=detail)
            db.add(inc)
            if _envoyer(db, f"Proprietas — {LIBELLES[code]}", detail):
                inc.dernier_envoi = maintenant
            bilan["ouverts"].append(code)
        else:
            inc.detail = detail
            if inc.dernier_envoi is None or maintenant - inc.dernier_envoi >= RAPPEL:
                if _envoyer(db, f"Proprietas — rappel : {LIBELLES[code]}",
                            f"Toujours en cours depuis le {inc.debut:%d/%m/%Y à %H:%M}.\n\n{detail}"):
                    inc.dernier_envoi = maintenant
                    bilan["rappels"].append(code)
    for code, inc in ouverts.items():
        if code not in presents:
            inc.fin = maintenant
            if inc.dernier_envoi is not None:
                _envoyer(db, f"Proprietas — résolu : {LIBELLES[code]}",
                         f"Problème apparu le {inc.debut:%d/%m/%Y à %H:%M}, disparu le {maintenant:%d/%m/%Y à %H:%M}.\n\n"
                         f"Dernier état connu : {inc.detail}")
            bilan["resolus"].append(code)
    db.query(Incident).filter(Incident.fin.isnot(None), Incident.fin < maintenant - CONSERVATION).delete(
        synchronize_session=False)
    db.commit()
    return bilan


def recents(db: Session, heures: int) -> list[dict]:
    depuis = datetime.now() - timedelta(hours=max(heures, 24 * 7))
    q = db.query(Incident).filter((Incident.fin.is_(None)) | (Incident.fin >= depuis)).order_by(Incident.debut.desc())
    return [{"code": i.code, "libelle": LIBELLES.get(i.code, i.code), "debut": i.debut, "fin": i.fin,
             "en_cours": i.fin is None, "detail": i.detail} for i in q]
