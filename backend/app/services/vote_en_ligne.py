"""Vote en direct pendant l'AG (demande de Fred, 21/11/2026).

- Le syndic ouvre le vote d'une résolution à la fois, puis le clôt ; la clôture calcule le résultat (majorité).
- Votent depuis leur compte les copropriétaires présents ou en visioconférence (loi n° 65-557, art. 17-1 A), pour
  leurs lots et ceux de leurs mandants (art. 22) ; résolution sur une clé : seuls les lots de la clé (art. 24).
- Tant que le vote est ouvert, chacun peut changer son vote ; le décompte est visible de tous.
- Les votes sont ceux de la table `votes` : le syndic peut toujours les saisir ou les corriger à la main.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.ag import AG, AgReponse, Resolution, Vote
from app.models.lot import Lot
from app.models.user import User
from app.services import presences
from app.services.country_rules import calculer_statut_resolution

VOIX = ("pour", "contre", "abstention")


def est_ouverte(r: Resolution) -> bool:
    return r.vote_ouvert_le is not None and r.vote_clos_le is None


def etat_resolution(r: Resolution) -> str:
    """« ouvert », « clos » (vote en ligne terminé) ou "" (jamais ouvert)."""
    if est_ouverte(r):
        return "ouvert"
    return "clos" if r.vote_clos_le is not None else ""


def ouverte(ag: AG) -> Resolution | None:
    return next((r for r in ag.resolutions if est_ouverte(r)), None)


def ouvrir(db: Session, r: Resolution) -> None:
    ag = r.ag
    if ag.type_ag == "consultation_ecrite":
        raise HTTPException(422, "Une consultation écrite ne se vote pas en séance.")
    if ag.date > date.today():
        raise HTTPException(422, f"L'assemblée a lieu le {ag.date:%d/%m/%Y} : le vote s'ouvre le jour de la séance.")
    autre = ouverte(ag)
    if autre is not None and autre.id != r.id:
        raise HTTPException(409, f"Le vote de la résolution n° {autre.numero} est ouvert : clôturez-le d'abord.")
    from app.services import correspondance
    correspondance.appliquer(db, ag, r)       # votes par correspondance des absents : dans le décompte dès l'ouverture
    r.vote_ouvert_le, r.vote_clos_le = datetime.now(), None


def clore(r: Resolution) -> None:
    if not est_ouverte(r):
        raise HTTPException(409, "Le vote en ligne de cette résolution n'est pas ouvert.")
    r.vote_clos_le = datetime.now()


def _reponse(db: Session, ag: AG, user: User) -> AgReponse | None:
    return db.query(AgReponse).filter(AgReponse.ag_id == ag.id, AgReponse.personne_id == user.id).first()


def peut_voter(db: Session, ag: AG, user: User) -> bool:
    r = _reponse(db, ag, user)
    return r is not None and r.reponse in presences.PRESENTS


def mes_lots(db: Session, ag: AG, r: Resolution, user: User) -> list[dict]:
    """Lots pour lesquels `user` vote : les siens, puis ceux de ses mandants ; seulement ceux qui votent la résolution."""
    from app.services import cles
    lots_votants, _ = cles.votants(db, ag.copropriete_id, r)
    poids = {l.id: l.tantiemes for l in lots_votants}
    votes = {v.lot_id: v.voix for v in r.votes}
    tous = db.query(Lot).filter(Lot.copropriete_id == ag.copropriete_id).order_by(Lot.id).all()
    out = [{"lot_id": l.id, "numero": l.numero, "au_titre": "", "tantiemes": poids[l.id]}
           for l in tous if l.proprietaire_id == user.id and l.id in poids]
    mandants = db.query(AgReponse).filter(AgReponse.ag_id == ag.id, AgReponse.reponse == "pouvoir",
                                          AgReponse.mandataire_id == user.id).all()
    for m in sorted(mandants, key=lambda x: x.personne_id):
        out += [{"lot_id": l.id, "numero": l.numero, "au_titre": f"pouvoir de {presences.nom(m.personne)}",
                 "tantiemes": poids[l.id]}
                for l in tous if l.proprietaire_id == m.personne_id and l.id in poids]
    for x in out:
        v = votes.get(x["lot_id"])
        x["voix"] = v if v in VOIX else None
    return out


def voter(db: Session, ag: AG, r: Resolution, user: User, voix: str, lot_ids: list[int] | None) -> int:
    """Enregistre le vote de `user` (tous ses lots, ou `lot_ids`) ; nombre de lots votés."""
    if not est_ouverte(r):
        raise HTTPException(409, "Le vote de cette résolution n'est pas ouvert.")
    if not peut_voter(db, ag, user):
        raise HTTPException(403, "Seuls les copropriétaires présents ou en visioconférence votent en ligne.")
    if voix not in VOIX:
        raise HTTPException(422, "Vote : pour, contre ou abstention.")
    possibles = {x["lot_id"] for x in mes_lots(db, ag, r, user)}
    choisis = set(lot_ids) if lot_ids else possibles
    if not choisis or not choisis <= possibles:
        raise HTTPException(422, "Vous ne votez pas pour ce lot sur cette résolution.")
    existants = {v.lot_id: v for v in db.query(Vote).filter(Vote.resolution_id == r.id, Vote.lot_id.in_(choisis))}
    for lot_id in choisis:
        if lot_id in existants:
            existants[lot_id].voix = voix
        else:
            db.add(Vote(resolution_id=r.id, lot_id=lot_id, voix=voix))
    db.flush()
    return len(choisis)


def etat(db: Session, ag: AG, user: User) -> dict:
    """Ce que voit chacun pendant la séance : la résolution ouverte, ses lots et son vote, le décompte."""
    r = ouverte(ag)
    if r is None:
        return {"resolution": None, "peut_voter": False, "mes_lots": [], "decompte": None}
    db.refresh(r)
    from app.services import cles
    lots, votes = cles.votants(db, ag.copropriete_id, r)
    res = calculer_statut_resolution(r, lots, votes)
    return {
        "resolution": {"id": r.id, "numero": r.numero, "libelle": r.libelle, "texte": r.texte or "",
                       "majorite": r.majorite, "ouvert_le": r.vote_ouvert_le},
        "peut_voter": peut_voter(db, ag, user),
        "mes_lots": mes_lots(db, ag, r, user),
        "decompte": {"pour": res["pour"], "contre": res["contre"], "abstention": res["abstention"],
                     "total": res["total"], "votants": sum(1 for v in votes if v.voix in VOIX)},
    }
