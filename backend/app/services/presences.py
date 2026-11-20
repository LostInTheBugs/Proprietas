"""AG : présence des copropriétaires et pouvoirs (demande de Fred, 19/11/2026).

Chaque copropriétaire (compte propriétaire d'au moins un lot) répond à l'information sur l'AG, par le lien
de l'e-mail ou depuis son compte : « Je serai présent(e) », « Je ne serai pas présent(e) et je donne
pouvoir à… » (un autre copropriétaire), « Je ne serai pas présent(e) », « Je ne sais pas encore ». Il peut
changer d'avis jusqu'à l'ouverture de l'AG ; le syndic, lui, corrige à tout moment (feuille de présence
tenue en séance, réponse reçue par téléphone ou par courrier).

Pouvoirs (loi n° 65-557 du 10 juillet 1965, art. 22) :
- le mandataire est un autre copropriétaire, jamais le syndic (ni son conjoint, partenaire, parents ou
  préposés : l'application ne peut pas le vérifier, la page le rappelle) ;
- au plus trois délégations par mandataire, sauf si ses voix et celles de ses mandants ne dépassent pas
  10 % des voix du syndicat (voix avec la réduction de l'art. 22, comme pour les votes) ;
- un pouvoir est un écrit : en plus de la désignation en ligne (datée, tracée), l'application produit le
  pouvoir en PDF, à signer et à remettre ; le syndic note sa réception (`pouvoir_recu_le`).
"""
from __future__ import annotations

from datetime import datetime, time
from fractions import Fraction

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.ag import AG, AgReponse
from app.models.lot import Lot
from app.models.user import User, UserCopro
from app.services.country_rules import poids_de_vote

REPONSES = {
    "present": "Je serai présent(e)",
    "pouvoir": "Je ne serai pas présent(e) et je donne pouvoir",
    "absent": "Je ne serai pas présent(e)",
    "incertain": "Je ne sais pas encore",
}
LIBELLES_COURTS = {"present": "Présent", "pouvoir": "Représenté", "absent": "Absent", "incertain": "Incertain",
                   "correspondance": "Vote par correspondance"}
MAX_DELEGATIONS = 3
PART_MAX = Fraction(1, 10)


def nom(u: User | None) -> str:
    return (u.nom_complet or u.email) if u is not None else "compte supprimé"


def ouverture(ag: AG) -> datetime:
    """Début de l'AG (sans heure : fin de la journée)."""
    try:
        h, m = (int(x) for x in (ag.heure or "").split(":")[:2])
        return datetime.combine(ag.date, time(h, m))
    except ValueError:
        return datetime.combine(ag.date, time(23, 59))


def reponses_ouvertes(ag: AG, maintenant: datetime | None = None) -> bool:
    """Le copropriétaire peut-il encore répondre ou changer d'avis ?"""
    return ag.statut != "terminee" and (maintenant or datetime.now()) < ouverture(ag)


def _lots(db: Session, copro_id: int) -> list[Lot]:
    return db.query(Lot).filter(Lot.copropriete_id == copro_id).order_by(Lot.id).all()


def coproprietaires(db: Session, copro_id: int) -> list[User]:
    """Comptes propriétaires d'au moins un lot de la copropriété."""
    ids = {l.proprietaire_id for l in _lots(db, copro_id) if l.proprietaire_id}
    return db.query(User).filter(User.id.in_(ids)).order_by(User.nom, User.prenom).all() if ids else []


def est_syndic(db: Session, copro_id: int, u: User) -> bool:
    return u.role == "syndic" and db.query(UserCopro).filter(
        UserCopro.user_id == u.id, UserCopro.copropriete_id == copro_id).first() is not None


def mandataires_possibles(db: Session, copro_id: int, mandant: User | None = None) -> list[User]:
    return [u for u in coproprietaires(db, copro_id)
            if (mandant is None or u.id != mandant.id) and not est_syndic(db, copro_id, u)]


def _parts(db: Session, copro_id: int) -> tuple[dict[int, Fraction], Fraction]:
    """Voix de chaque copropriétaire (réduction art. 22 comprise) et total des voix."""
    lots = _lots(db, copro_id)
    poids = poids_de_vote(lots)
    voix: dict[int, Fraction] = {}
    for l in lots:
        if l.proprietaire_id:
            voix[l.proprietaire_id] = voix.get(l.proprietaire_id, Fraction(0)) + Fraction(poids.get(l.id, 0))
    return voix, sum((Fraction(p) for p in poids.values()), Fraction(0))


def controler_mandat(db: Session, ag: AG, mandant: User, mandataire_id: int | None) -> User:
    """Le mandataire choisi, s'il respecte l'art. 22 ; 422 sinon."""
    if mandataire_id is None:
        raise HTTPException(422, "Choisissez le copropriétaire à qui vous donnez pouvoir.")
    mandataire = db.get(User, mandataire_id)
    if mandataire is None or mandataire.id == mandant.id or mandataire not in coproprietaires(db, ag.copropriete_id):
        raise HTTPException(422, "Le pouvoir se donne à un autre copropriétaire de l'immeuble.")
    if est_syndic(db, ag.copropriete_id, mandataire):
        raise HTTPException(422, "Le syndic ne peut pas recevoir de pouvoir (loi du 10 juillet 1965, art. 22) : "
                                 "choisissez un autre copropriétaire.")
    autres = [r.personne_id for r in db.query(AgReponse).filter(
        AgReponse.ag_id == ag.id, AgReponse.reponse == "pouvoir", AgReponse.mandataire_id == mandataire.id,
        AgReponse.personne_id != mandant.id)]
    if len(autres) + 1 > MAX_DELEGATIONS:
        voix, total = _parts(db, ag.copropriete_id)
        cumul = sum((voix.get(p, Fraction(0)) for p in [mandataire.id, mandant.id, *autres]), Fraction(0))
        if total and cumul / total > PART_MAX:
            raise HTTPException(422, f"{nom(mandataire)} a déjà {len(autres)} pouvoirs : au-delà de trois, ses voix "
                                     "et celles de ses mandants ne doivent pas dépasser 10 % des voix du syndicat "
                                     f"(art. 22) ; ici {float(cumul / total) * 100:.1f} %. Choisissez un autre "
                                     "copropriétaire.")
    return mandataire


def repondre(db: Session, ag: AG, personne: User, reponse: str, mandataire_id: int | None, source: str) -> AgReponse:
    """Enregistre (ou change) la réponse ; l'appelant fait le commit."""
    if reponse not in REPONSES:
        raise HTTPException(422, "Réponse inconnue.")
    if personne not in coproprietaires(db, ag.copropriete_id):
        raise HTTPException(422, "Seuls les copropriétaires répondent à l'information sur l'AG.")
    mandataire = controler_mandat(db, ag, personne, mandataire_id) if reponse == "pouvoir" else None
    r = db.query(AgReponse).filter(AgReponse.ag_id == ag.id, AgReponse.personne_id == personne.id).first()
    if r is None:
        r = AgReponse(ag_id=ag.id, personne_id=personne.id)
        db.add(r)
    nouveau_mandataire = mandataire.id if mandataire else None
    if r.mandataire_id != nouveau_mandataire or reponse != "pouvoir":
        r.pouvoir_recu_le = None              # le pouvoir signé reçu ne vaut que pour ce mandataire
    r.reponse, r.mandataire_id, r.repondu_le, r.source = reponse, nouveau_mandataire, datetime.now(), source
    db.flush()
    return r


def etat(db: Session, ag: AG) -> dict:
    """Une ligne par copropriétaire (réponse, mandataire, lots, voix) et les totaux."""
    voix, total = _parts(db, ag.copropriete_id)
    lots = _lots(db, ag.copropriete_id)
    reponses = {r.personne_id: r for r in db.query(AgReponse).filter(AgReponse.ag_id == ag.id)}
    from app.models.ag import VoteCorrespondance
    recus = {vc.personne_id: vc.recu_le for vc in db.query(VoteCorrespondance).filter(VoteCorrespondance.ag_id == ag.id)}
    lignes = []
    for u in coproprietaires(db, ag.copropriete_id):
        r = reponses.get(u.id)
        mandataire = r.mandataire if r is not None and r.reponse == "pouvoir" else None
        mandataire_absent = bool(mandataire and mandataire.id in reponses
                                 and reponses[mandataire.id].reponse in ("absent", "pouvoir"))
        lignes.append({
            "personne_id": u.id, "nom": nom(u),
            "lots": [l.numero for l in lots if l.proprietaire_id == u.id],
            "voix": round(float(voix.get(u.id, 0) / total * 1000), 1) if total else 0.0,   # en millièmes
            "reponse": r.reponse if r else "", "repondu_le": r.repondu_le if r else None,
            "source": r.source if r else "",
            "mandataire_id": mandataire.id if mandataire else None, "mandataire_nom": nom(mandataire) if mandataire else "",
            "mandataire_absent": mandataire_absent,
            "pouvoir_recu_le": r.pouvoir_recu_le if r else None,
            "correspondance_recue_le": recus.get(u.id) if r is not None and r.reponse == "correspondance" else None,
            "mandats": sum(1 for x in reponses.values() if x.reponse == "pouvoir" and x.mandataire_id == u.id),
            "peut_recevoir_pouvoir": not est_syndic(db, ag.copropriete_id, u),
        })
    def total_voix(*rep):
        return round(sum(l["voix"] for l in lignes if l["reponse"] in rep), 1)
    return {
        "ouvert": reponses_ouvertes(ag),
        "lignes": lignes,
        "totaux": {
            "presents": sum(1 for l in lignes if l["reponse"] == "present"),
            "representes": sum(1 for l in lignes if l["reponse"] == "pouvoir"),
            "absents": sum(1 for l in lignes if l["reponse"] == "absent"),
            "incertains": sum(1 for l in lignes if l["reponse"] == "incertain"),
            "correspondances": sum(1 for l in lignes if l["reponse"] == "correspondance"),
            "voix_correspondance": total_voix("correspondance"),
            "sans_reponse": sum(1 for l in lignes if not l["reponse"]),
            "voix_presentes_ou_representees": total_voix("present", "pouvoir"),
        },
    }
