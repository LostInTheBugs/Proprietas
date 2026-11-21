"""Vote par correspondance (demande de Fred, 20/11/2026).

Règles (loi n° 65-557 du 10 juillet 1965, art. 17-1 A ; décret n° 67-223 du 17 mars 1967, art. 9, 9 bis, 14,
14-1 et 17 ; formulaire de l'arrêté du 2 juillet 2020) :
- le formulaire est joint à la convocation ; le copropriétaire y vote pour, contre ou abstention, résolution
  par résolution ;
- il doit parvenir au syndic au plus tard **trois jours francs** avant l'AG (envoi électronique : reçu à la
  date d'envoi) : pour une AG le jour J, le dernier jour de réception est J − 4 ;
- un formulaire sans sens de vote précis, ou qui exprime une abstention, compte comme un vote défavorable ;
- si la résolution est amendée en séance, un vote « pour » par correspondance compte comme défaillant ;
- le formulaire n'est pas pris en compte si le copropriétaire est présent ou représenté à l'AG ;
- la feuille de présence mentionne les votants par correspondance et la date de réception du formulaire.

Le syndic saisit le formulaire reçu ; les votes s'appliquent aux lots du copropriétaire, résolution par
résolution, au moment du calcul du résultat (et dès la saisie, pour l'affichage).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core import audit
from app.models.ag import AG, AgReponse, Resolution, Vote, VoteCorrespondance
from app.models.lot import Lot
from app.models.user import User
from app.services import presences

VOIX = ("pour", "contre", "abstention", "")
JOURS_FRANCS = 3


def date_limite(ag: AG) -> date:
    """Dernier jour de réception du formulaire : trois jours francs avant la réunion (J − 4)."""
    return ag.date - timedelta(days=JOURS_FRANCS + 1)


def resolutions_votables(ag: AG) -> list[Resolution]:
    """Résolutions du formulaire : toutes, sauf les seconds votes (passerelles), décidés en séance."""
    return sorted((r for r in ag.resolutions if r.second_vote_de_id is None), key=lambda r: r.numero)


def _personne(db: Session, ag: AG, personne_id: int) -> User:
    u = db.get(User, personne_id)
    if u is None or u not in presences.coproprietaires(db, ag.copropriete_id):
        raise HTTPException(422, "Seuls les copropriétaires votent par correspondance.")
    return u


def enregistrer(db: Session, ag: AG, personne_id: int, recu_le: date, votes: dict[int, str], user, request) -> None:
    """Saisie du formulaire reçu : remplace un formulaire déjà saisi pour cette personne."""
    if ag.type_ag == "consultation_ecrite":
        raise HTTPException(422, "Une consultation écrite n'a pas de vote par correspondance : chacun y répond par écrit.")
    u = _personne(db, ag, personne_id)
    if recu_le > date.today():
        raise HTTPException(422, "La date de réception ne peut pas être dans le futur.")
    if recu_le > date_limite(ag):
        raise HTTPException(422, f"Formulaire reçu trop tard : il devait parvenir au syndic au plus tard le "
                                 f"{date_limite(ag):%d/%m/%Y} (trois jours francs avant l'assemblée). Il n'est pas pris en compte.")
    ids = {r.id for r in resolutions_votables(ag)}
    inconnues = [k for k in votes if k not in ids]
    if inconnues:
        raise HTTPException(422, "Une résolution du formulaire n'appartient pas à cette assemblée.")
    if any(v not in VOIX for v in votes.values()):
        raise HTTPException(422, "Vote inconnu (pour, contre, abstention, ou case vide).")
    db.query(VoteCorrespondance).filter(VoteCorrespondance.ag_id == ag.id,
                                        VoteCorrespondance.personne_id == u.id).delete(synchronize_session=False)
    for rid in sorted(ids):
        db.add(VoteCorrespondance(ag_id=ag.id, resolution_id=rid, personne_id=u.id, voix=votes.get(rid, ""),
                                  recu_le=recu_le))
    r = db.query(AgReponse).filter(AgReponse.ag_id == ag.id, AgReponse.personne_id == u.id).first()
    if r is None:
        r = AgReponse(ag_id=ag.id, personne_id=u.id)
        db.add(r)
    r.reponse, r.mandataire_id, r.pouvoir_recu_le = "correspondance", None, None
    r.repondu_le, r.source = datetime.now(), "syndic"
    db.flush()
    appliquer(db, ag)
    audit.enregistrer(db, "vote_correspondance", user=user, copro_id=ag.copropriete_id, request=request,
                      detail=f"AG du {ag.date:%d/%m/%Y} : formulaire de {presences.nom(u)} reçu le {recu_le:%d/%m/%Y}")


def supprimer(db: Session, ag: AG, personne_id: int, user, request) -> None:
    u = _personne(db, ag, personne_id)
    lots = [l.id for l in db.query(Lot).filter(Lot.copropriete_id == ag.copropriete_id, Lot.proprietaire_id == u.id)]
    for vc in db.query(VoteCorrespondance).filter(VoteCorrespondance.ag_id == ag.id, VoteCorrespondance.personne_id == u.id):
        db.query(Vote).filter(Vote.resolution_id == vc.resolution_id, Vote.lot_id.in_(lots)).delete(synchronize_session=False)
        db.delete(vc)
    r = db.query(AgReponse).filter(AgReponse.ag_id == ag.id, AgReponse.personne_id == u.id).first()
    if r is not None and r.reponse == "correspondance":
        db.delete(r)
    db.flush()
    audit.enregistrer(db, "vote_correspondance_retire", user=user, copro_id=ag.copropriete_id, request=request,
                      detail=f"AG du {ag.date:%d/%m/%Y} : formulaire de {presences.nom(u)}")


def voix_retenue(vc: VoteCorrespondance, resolution: Resolution) -> str:
    """Vote compté : abstention ou case vide → contre ; « pour » sur une résolution amendée → défaillant (null)."""
    if vc.voix == "pour":
        return "null" if resolution.amendee else "pour"
    return "contre"


def appliquer(db: Session, ag: AG, resolution: Resolution | None = None) -> int:
    """Reporte les votes par correspondance sur les lots des copropriétaires ni présents ni représentés."""
    reponses = {r.personne_id: r.reponse for r in db.query(AgReponse).filter(AgReponse.ag_id == ag.id)}
    q = db.query(VoteCorrespondance).filter(VoteCorrespondance.ag_id == ag.id)
    if resolution is not None:
        q = q.filter(VoteCorrespondance.resolution_id == resolution.id)
    n = 0
    for vc in q:
        if reponses.get(vc.personne_id) in ("present", "visio", "pouvoir"):
            continue                       # présent ou représenté : le formulaire n'est pas pris en compte
        res = db.get(Resolution, vc.resolution_id)
        voix = voix_retenue(vc, res)
        for lot in db.query(Lot).filter(Lot.copropriete_id == ag.copropriete_id, Lot.proprietaire_id == vc.personne_id):
            v = db.query(Vote).filter(Vote.resolution_id == res.id, Vote.lot_id == lot.id).first()
            if v is None:
                db.add(Vote(resolution_id=res.id, lot_id=lot.id, voix=voix))
            else:
                v.voix = voix
            n += 1
    db.flush()
    return n


def etat(db: Session, ag: AG) -> dict:
    lignes = {}
    for vc in db.query(VoteCorrespondance).filter(VoteCorrespondance.ag_id == ag.id):
        l = lignes.setdefault(vc.personne_id, {"personne_id": vc.personne_id,
                                               "nom": presences.nom(db.get(User, vc.personne_id)),
                                               "recu_le": vc.recu_le, "votes": {}})
        l["votes"][vc.resolution_id] = vc.voix
    reponses = {r.personne_id: r.reponse for r in db.query(AgReponse).filter(AgReponse.ag_id == ag.id)}
    for l in lignes.values():
        l["ecarte"] = reponses.get(l["personne_id"]) in ("present", "visio", "pouvoir")
    return {"date_limite": date_limite(ag), "formulaires": sorted(lignes.values(), key=lambda l: l["nom"])}
