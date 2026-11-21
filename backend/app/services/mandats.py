"""Mandats du syndic bénévole et du conseil syndical (demande de Fred, 21/11/2026).

- Durée : trois ans au plus, pour le syndic (décret n° 67-223 du 17 mars 1967, art. 28) comme pour les membres du
  conseil syndical (même décret, art. 22). Désignation à la majorité de l'art. 25 (loi n° 65-557, art. 25).
- Une résolution « syndic » ou « conseil » adoptée enregistre le mandat, du jour de l'AG pour la durée votée ; le
  mandat suit la résolution (recalcul, modification, suppression) et l'AG (date, suppression) : `synchroniser`.
- Un mandat passé se saisit à la main : date de début, ou AG de l'application dont la date est reprise.
- Échéance : alerte six mois avant la fin ; les résolutions types de l'AG annuelle sont cochées quand le mandat
  finit avant l'AG annuelle suivante (services/modele_ag.py).
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.ag import AG, Resolution
from app.models.mandat import Mandat
from app.models.user import User, UserCopro

ROLES = {"syndic": "Syndic bénévole", "conseil": "Conseil syndical"}
DUREE_MAX_MOIS = 36
PREAVIS_JOURS = 183           # alerte six mois avant la fin


def plus_mois(d: date, mois: int) -> date:
    a, m = divmod(d.month - 1 + mois, 12)
    an, mo = d.year + a, m + 1
    return date(an, mo, min(d.day, calendar.monthrange(an, mo)[1]))


def fin_mandat(debut: date, mois: int) -> date:
    """Dernier jour d'un mandat de `mois` mois commencé le `debut`."""
    return plus_mois(debut, mois) - timedelta(days=1)


def _nom(u: User | None) -> str:
    return (u.nom_complet or u.email) if u is not None else "compte supprimé"


def controler(db: Session, copro_id: int, role: str, mois: int | None, personne_ids: list[int] | None,
              noms: list[str] | None = None, exiger: bool = False) -> None:
    """422 si le rôle, la durée ou les personnes ne conviennent pas. `exiger` : durée et membres obligatoires."""
    if role not in ROLES:
        raise HTTPException(422, f"Rôle inconnu : {role} (syndic | conseil).")
    if mois is not None and not 1 <= mois <= DUREE_MAX_MOIS:
        raise HTTPException(422, f"{ROLES[role]} : mandat de {DUREE_MAX_MOIS} mois au plus (trois ans ; décret "
                                 f"n° 67-223, art. {28 if role == 'syndic' else 22}).")
    ids = list(personne_ids or [])
    noms = [n.strip() for n in (noms or []) if n and n.strip()]
    if exiger and (mois is None or not (ids or noms)):
        raise HTTPException(422, "Indiquez la durée du mandat et au moins une personne.")
    if role == "syndic" and len(ids) + len(noms) > 1:
        raise HTTPException(422, "Un seul syndic.")
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "Une même personne figure deux fois.")
    if ids:
        membres = {u for (u,) in db.query(UserCopro.user_id).filter(UserCopro.copropriete_id == copro_id)}
        inconnus = [i for i in ids if i not in membres]
        if inconnus:
            raise HTTPException(422, "Personne inconnue dans la copropriété : choisissez un compte de la copropriété.")


def personnes(db: Session, copro_id: int) -> list[dict]:
    """Comptes de la copropriété (hors démonstration), par nom."""
    us = (db.query(User).join(UserCopro, UserCopro.user_id == User.id)
          .filter(UserCopro.copropriete_id == copro_id, User.is_demo.isnot(True)).all())
    return sorted(({"id": u.id, "nom": _nom(u)} for u in us), key=lambda x: x["nom"].lower())


def _membres(db: Session, personne_ids: list[int], noms: list[str] | None = None) -> list[dict]:
    out = [{"personne_id": i, "nom": _nom(db.get(User, i))} for i in personne_ids]
    return out + [{"personne_id": None, "nom": n.strip()} for n in (noms or []) if n and n.strip()]


def synchroniser(db: Session, r: Resolution) -> None:
    """Recrée le mandat d'une résolution « syndic » / « conseil » : présent si elle est adoptée, absent sinon."""
    db.query(Mandat).filter(Mandat.resolution_id == r.id).delete(synchronize_session=False)
    if (r.nature in ROLES and r.statut == "adoptee" and r.mandat_mois and r.mandat_personnes
            and r.ag is not None):
        db.add(Mandat(copropriete_id=r.ag.copropriete_id, role=r.nature, debut=r.ag.date,
                      fin=fin_mandat(r.ag.date, r.mandat_mois), membres=_membres(db, list(r.mandat_personnes)),
                      ag_id=r.ag_id, resolution_id=r.id))


def retirer_ag(db: Session, ag: AG) -> None:
    """AG supprimée : ses mandats votés disparaissent ; un mandat saisi à la main garde sa date, sans l'AG."""
    ids = [r.id for r in ag.resolutions]
    if ids:
        db.query(Mandat).filter(Mandat.resolution_id.in_(ids)).delete(synchronize_session=False)
    db.query(Mandat).filter(Mandat.ag_id == ag.id).update({Mandat.ag_id: None}, synchronize_session=False)


def creer(db: Session, copro_id: int, role: str, debut: date | None, mois: int, personne_ids: list[int],
          noms: list[str], ag_id: int | None) -> Mandat:
    """Mandat passé saisi à la main."""
    controler(db, copro_id, role, mois, personne_ids, noms, exiger=True)
    if ag_id is not None:
        ag = db.query(AG).filter(AG.id == ag_id, AG.copropriete_id == copro_id).first()
        if ag is None:
            raise HTTPException(404, "AG introuvable")
        debut = ag.date
    if debut is None:
        raise HTTPException(422, "Indiquez la date de début du mandat ou l'AG qui l'a voté.")
    if debut > date.today():
        raise HTTPException(422, "Un mandat saisi à la main est un mandat passé ou en cours : date future refusée.")
    m = Mandat(copropriete_id=copro_id, role=role, debut=debut, fin=fin_mandat(debut, mois),
               membres=_membres(db, personne_ids, noms), ag_id=ag_id)
    db.add(m)
    db.flush()
    return m


def _out(db: Session, m: Mandat) -> dict:
    ag = db.get(AG, m.ag_id) if m.ag_id else None
    res = db.get(Resolution, m.resolution_id) if m.resolution_id else None
    membres = [{"personne_id": x.get("personne_id"),
                "nom": _nom(db.get(User, x["personne_id"])) if x.get("personne_id") else x.get("nom", "")}
               for x in (m.membres or [])]
    return {"id": m.id, "role": m.role, "debut": m.debut, "fin": m.fin, "membres": membres,
            "ag_id": m.ag_id, "ag_date": ag.date if ag else None, "resolution_id": m.resolution_id,
            "resolution_numero": res.numero if res else None, "manuel": m.resolution_id is None}


def etat(fin: date | None, jour: date) -> str:
    if fin is None:
        return "aucun"
    if fin < jour:
        return "echu"
    return "bientot" if (fin - jour).days <= PREAVIS_JOURS else "en_cours"


def dernier(db: Session, copro_id: int, role: str) -> Mandat | None:
    return (db.query(Mandat).filter(Mandat.copropriete_id == copro_id, Mandat.role == role)
            .order_by(Mandat.debut.desc(), Mandat.id.desc()).first())


def situation(db: Session, copro_id: int, jour: date | None = None) -> dict:
    """Par rôle : mandat en cours (ou None), état (en_cours | bientot | echu | aucun), historique ; et les alertes."""
    jour = jour or date.today()
    out: dict = {"alertes": []}
    for role, libelle in ROLES.items():
        tous = (db.query(Mandat).filter(Mandat.copropriete_id == copro_id, Mandat.role == role)
                .order_by(Mandat.debut.desc(), Mandat.id.desc()).all())
        actuel = next((m for m in tous if m.debut <= jour <= m.fin), None)
        e = etat(actuel.fin if actuel else (tous[0].fin if tous else None), jour)
        if e == "bientot":
            out["alertes"].append(f"{libelle} : le mandat finit le {actuel.fin:%d/%m/%Y}. Prévoyez la "
                                  f"{'désignation du syndic' if role == 'syndic' else 'élection du conseil syndical'} "
                                  "à la prochaine AG.")
        elif e == "echu":
            out["alertes"].append(f"{libelle} : mandat échu depuis le {tous[0].fin:%d/%m/%Y}.")
        out[role] = {"libelle": libelle, "etat": e, "actuel": _out(db, actuel) if actuel else None,
                     "historique": [_out(db, m) for m in tous]}
    return out
