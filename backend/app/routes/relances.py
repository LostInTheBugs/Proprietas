from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_user, require_syndic
from app.models.user import User
from app.models.lot import Lot
from app.models.appel import AppelLot
from app.models.mouvement import Mouvement
from app.models.relance import Relance
from app.models.copropriete import Copropriete
from app.routes.copro import get_or_create_copro
from app.services.emailer import envoyer_email, relance_texte, EmailError
from app.schemas import RelanceLotOut, RelanceEnvoiIn, RelanceOut, InvitationsResult

router = APIRouter(prefix="/api/relances", tags=["relances"])


def _etat_lots(db: Session, copro: Copropriete) -> list[dict]:
    """Solde par lot : appels (charges + fonds travaux) − encaissements du lot.

    Le propriétaire est le compte utilisateur (modèle « zéro fiche »).
    """
    lots = db.query(Lot).filter(Lot.copropriete_id == copro.id).all()
    result = []
    for lot in lots:
        appels_c = sum(a.montant_charges for a in db.query(AppelLot).filter(AppelLot.lot_id == lot.id).all())
        appels_f = sum(a.montant_fonds_travaux for a in db.query(AppelLot).filter(AppelLot.lot_id == lot.id).all())
        enc = sum(m.montant for m in db.query(Mouvement).filter(
            Mouvement.lot_id == lot.id, Mouvement.type == "encaissement").all())
        personne = db.query(User).filter(User.id == lot.proprietaire_id).first() if lot.proprietaire_id else None
        result.append({
            "lot": lot,
            "personne": personne,
            "appels_charges": round(appels_c, 2),
            "appels_fonds": round(appels_f, 2),
            "encaisse": round(enc, 2),
            "solde": round(appels_c + appels_f - enc, 2),
        })
    return result


@router.get("", response_model=list[RelanceLotOut])
def liste_etat(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """État des impayés par lot (tous les lots, avec leur solde)."""
    copro = get_or_create_copro(db, user)
    out = []
    for e in _etat_lots(db, copro):
        p = e["personne"]
        out.append(RelanceLotOut(
            lot_id=e["lot"].id,
            lot_numero=e["lot"].numero,
            personne_id=p.id if p else None,
            personne_nom=f"{p.prenom} {p.nom}".strip() if p else "—",
            personne_email=p.email if p else "",
            appels_charges=e["appels_charges"],
            appels_fonds=e["appels_fonds"],
            encaisse=e["encaisse"],
            solde=e["solde"],
        ))
    return out


def envoyer_relance_lot(db: Session, copro: Copropriete, e: dict, syndic_nom: str,
                        acteur: User | None = None, request: Request | None = None) -> str:
    """Envoie la relance d'un lot et journalise (retour : envoye | sans_email | erreur).

    `acteur` = syndic à l'origine de l'envoi manuel ; None pour l'envoi automatique
    (cron) — le journal d'audit distingue les deux.
    """
    p = e["personne"]
    if not p or not p.email:
        return "sans_email"
    corps = relance_texte(
        copro, e["lot"].numero, p.prenom or p.nom,
        e["solde"], e["appels_charges"], e["appels_fonds"], e["encaisse"],
        syndic_nom,
    )
    sujet = f"Rappel de règlement — lot {e['lot'].numero} — {copro.nom}"
    try:
        envoyer_email(copro, p.email, sujet, corps)
        statut = "envoye"
        message = ""
    except EmailError as ex:
        statut = "erreur"
        message = str(ex)
    db.add(Relance(
        lot_id=e["lot"].id, personne_id=p.id if p else None,
        date_envoi=datetime.now(), statut=statut,
        montant_du=e["solde"], message=message,
    ))
    audit.enregistrer(
        db, "relance_envoyee", user=acteur, copro_id=copro.id, request=request,
        detail=(f"Lot {e['lot'].numero} → {p.email} "
                f"({'automatique' if acteur is None else 'manuelle'}, {statut})"),
    )
    return statut


@router.post("/envoyer", response_model=InvitationsResult)
def envoyer_relances(data: RelanceEnvoiIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Envoie une relance par email aux propriétaires des lots sélectionnés (ceux en retard)."""
    copro = get_or_create_copro(db, user)
    lots_par_id = {e["lot"].id: e for e in _etat_lots(db, copro)}

    envoyes = 0
    sans_email = 0
    erreurs = []
    for lot_id in data.lot_ids:
        e = lots_par_id.get(lot_id)
        if not e or e["solde"] <= 0.005:
            continue  # lot inconnu ou sans impayé
        statut = envoyer_relance_lot(db, copro, e, user.nom or "Le syndic",
                                     acteur=user, request=request)
        if statut == "envoye":
            envoyes += 1
        elif statut == "sans_email":
            sans_email += 1
        else:
            erreurs.append(f"Lot {e['lot'].numero}: {e['personne'].prenom} {e['personne'].nom}")
    db.commit()
    return InvitationsResult(envoyes=envoyes, sans_email=sans_email, erreurs=erreurs)


@router.get("/prochaine")
def prochaine(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Prochaine date d'envoi des relances automatiques (null si désactivé)."""
    from app.services.relance_auto import prochaine_relance
    copro = get_or_create_copro(db, user)
    p = prochaine_relance(copro)
    return {"prochaine": p.isoformat() if p else None}


@router.get("/historique", response_model=list[RelanceOut])
def historique(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Dernières relances envoyées."""
    copro = get_or_create_copro(db, user)
    relances = db.query(Relance).join(Lot).filter(
        Lot.copropriete_id == copro.id,
    ).order_by(Relance.date_envoi.desc()).limit(50).all()
    out = []
    for r in relances:
        lot = db.query(Lot).filter(Lot.id == r.lot_id).first()
        p = db.query(User).filter(User.id == r.personne_id).first()
        out.append(RelanceOut(
            id=r.id,
            lot_id=r.lot_id,
            lot_numero=lot.numero if lot else "",
            personne_nom=f"{p.prenom} {p.nom}".strip() if p else "",
            personne_email=p.email if p else "",
            date_envoi=r.date_envoi,
            statut=r.statut,
            montant_du=r.montant_du,
            message=r.message,
        ))
    return out
