"""Supervision externe : GET /api/metrics, format texte de Prometheus (demande de Fred, 22/11/2026).

Protégé par le jeton COPRO_METRICS_TOKEN (en-tête « Authorization: Bearer … », comparaison à temps constant) ;
sans jeton configuré, la route n'existe pas (404). Aucune donnée personnelle : des nombres seulement.
"""
import hmac
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.version import VERSION

router = APIRouter(prefix="/api", tags=["supervision"])


def _ligne(nom, valeur, aide=None, type_=None, etiquettes=""):
    out = []
    if aide:
        out += [f"# HELP {nom} {aide}", f"# TYPE {nom} {type_}"]
    if valeur is not None:
        out.append(f"{nom}{etiquettes} {valeur}")
    return out


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(request: Request, db: Session = Depends(get_db)):
    jeton = get_settings().metrics_token
    if not jeton:
        raise HTTPException(404, "Not Found")
    recu = request.headers.get("authorization", "")
    if not hmac.compare_digest(recu.encode(), f"Bearer {jeton}".encode()):
        raise HTTPException(401, "Jeton de supervision invalide")
    from app.models.copropriete import Copropriete
    from app.models.supervision import Incident, MesureServeur
    from app.models.user import User
    from app.services import supervision
    t = supervision.totaux
    m = db.query(MesureServeur).order_by(MesureServeur.instant.desc()).first()
    lignes = []
    lignes += _ligne("proprietas_info", 1, "Version de l'application.", "gauge", f'{{version="{VERSION}"}}')
    lignes += _ligne("proprietas_requetes_total", t["requetes"], "Requêtes de l'API depuis le démarrage.", "counter")
    lignes += _ligne("proprietas_erreurs_5xx_total", t["erreurs"], "Erreurs serveur (5xx) depuis le démarrage.", "counter")
    lignes += ["# HELP proprietas_requete_duree_secondes Durée des requêtes de l'API.",
               "# TYPE proprietas_requete_duree_secondes histogram"]
    cumul = 0
    for seuil, n in zip(list(supervision.SEUILS_DUREE) + ["+Inf"], t["seaux"]):
        cumul += n
        lignes.append(f'proprietas_requete_duree_secondes_bucket{{le="{seuil}"}} {cumul}')
    lignes += [f"proprietas_requete_duree_secondes_sum {round(t['somme_durees'], 6)}",
               f"proprietas_requete_duree_secondes_count {t['requetes']}"]
    for nom, champ, aide in (("proprietas_cpu_pct", "cpu_pct", "Processeur (dernier relevé), en %."),
                             ("proprietas_memoire_pct", "memoire_pct", "Mémoire utilisée (dernier relevé), en %."),
                             ("proprietas_disque_pct", "disque_pct", "Disque utilisé (dernier relevé), en %.")):
        lignes += _ligne(nom, getattr(m, champ) if m and getattr(m, champ) is not None else "NaN", aide, "gauge")
    lignes += _ligne("proprietas_dernier_releve_timestamp", round(m.instant.timestamp()) if m else 0,
                     "Instant du dernier relevé de supervision (secondes Unix).", "gauge")
    lignes += _ligne("proprietas_incidents_en_cours", db.query(Incident).filter(Incident.fin.is_(None)).count(),
                     "Incidents de supervision en cours.", "gauge")
    lignes += _ligne("proprietas_coproprietes", db.query(Copropriete).count(), "Copropriétés de l'instance.", "gauge")
    lignes += _ligne("proprietas_utilisateurs", db.query(User).filter(User.is_demo.isnot(True)).count(),
                     "Comptes (hors démonstration).", "gauge")
    lignes += _ligne("proprietas_sauvegardes_drive_en_echec",
                     db.query(Copropriete).filter(Copropriete.drive_sauvegarde_erreur.isnot(None),
                                                  Copropriete.drive_sauvegarde_erreur != "").count(),
                     "Copropriétés dont la sauvegarde automatique sur le drive est en échec.", "gauge")
    lignes += _ligne("proprietas_heure_timestamp", round(time.time()), "Heure du serveur (secondes Unix).", "gauge")
    return PlainTextResponse("\n".join(lignes) + "\n", media_type="text/plain; version=0.0.4; charset=utf-8")
