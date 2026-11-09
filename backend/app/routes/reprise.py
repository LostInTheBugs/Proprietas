"""Reprise de l'historique : états de fin d'exercice (31/12), base et points de contrôle.

Réservé au syndic ; chaque création, modification, suppression et validation est auditée.
Règles : services/reprise.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core import audit
from app.core.database import get_db
from app.core.deps import require_syndic
from app.core.money import D, arrondi, somme
from app.core.scoping import get_owned
from app.models.lot import Lot
from app.models.reprise import EtatReprise, EtatRepriseLigne
from app.models.user import User
from app.routes.copro import get_or_create_copro
from app.schemas import (EtatRepriseDetail, EtatRepriseIn, EtatRepriseOut, ImportRepriseIn,
                         ImportRepriseOut, SoldesBanqueIn)
from app.services import reprise as svc
from app.services import reprise_import

router = APIRouter(prefix="/api/reprise", tags=["reprise"])


def _out(db: Session, copro_id: int, etat: EtatReprise, b, detail: bool = False):
    ctrls = svc.controles(db, copro_id, etat)
    banque = svc.controles_banque(db, copro_id, etat)
    champs = dict(
        id=etat.id, date=etat.date, valide=bool(etat.valide), valide_le=etat.valide_le,
        role=svc.role(etat, b), commentaire=etat.commentaire or "",
        total_charges=arrondi(somme(D(l.montant_charges or 0) for l in etat.lignes)),
        total_fonds_travaux=arrondi(somme(D(l.montant_fonds_travaux or 0) for l in etat.lignes)),
        nb_lignes=len(etat.lignes),
        controle_ok=all(c["ok"] for c in ctrls) if ctrls else None,
        solde_banque=etat.solde_banque, solde_banque_fonds=etat.solde_banque_fonds,
        banque_ok=all(c["ok"] for c in banque) if banque else None,
    )
    if not detail:
        return EtatRepriseOut(**champs)
    lignes = [dict(id=l.id, lot_id=l.lot_id, lot_numero=l.lot.numero if l.lot else "",
                   proprietaire_id=l.proprietaire_id, exercice_origine=l.exercice_origine,
                   montant_charges=l.montant_charges, montant_fonds_travaux=l.montant_fonds_travaux)
              for l in etat.lignes]
    return EtatRepriseDetail(**champs, lignes=lignes, controles=ctrls, controles_banque=banque)


def _etat(db: Session, etat_id: int, copro) -> EtatReprise:
    return get_owned(db, EtatReprise, etat_id, copro, label="État de reprise")


def _remplir(db: Session, etat: EtatReprise, data: EtatRepriseIn) -> None:
    etat.solde_banque = data.solde_banque
    etat.solde_banque_fonds = data.solde_banque_fonds
    proprietaires = {l.id: l.proprietaire_id for l in db.query(Lot).filter(Lot.copropriete_id == etat.copropriete_id)}
    etat.lignes = [EtatRepriseLigne(
        lot_id=l.lot_id, exercice_origine=l.exercice_origine,
        proprietaire_id=l.proprietaire_id if l.proprietaire_id is not None else proprietaires.get(l.lot_id),
        montant_charges=l.montant_charges, montant_fonds_travaux=l.montant_fonds_travaux,
    ) for l in data.lignes]


def _doublon(db: Session, copro_id: int, data: EtatRepriseIn, sauf_id: int | None = None) -> None:
    q = db.query(EtatReprise).filter(EtatReprise.copropriete_id == copro_id, EtatReprise.date == data.date)
    if sauf_id is not None:
        q = q.filter(EtatReprise.id != sauf_id)
    if q.first():
        raise HTTPException(409, f"Un état au {data.date:%d/%m/%Y} existe déjà.")


@router.get("/etats", response_model=list[EtatRepriseOut])
def liste(db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    b, etats = svc.roles(db, copro.id)
    return [_out(db, copro.id, e, b) for e in etats]


@router.get("/etats/{etat_id}", response_model=EtatRepriseDetail)
def detail(etat_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    etat = _etat(db, etat_id, copro)
    return _out(db, copro.id, etat, svc.base(db, copro.id), detail=True)


@router.post("/etats", response_model=EtatRepriseDetail)
def creer(data: EtatRepriseIn, request: Request, db: Session = Depends(get_db),
          user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    svc.controler_saisie(db, copro.id, data.date, data.lignes)
    _doublon(db, copro.id, data)
    etat = EtatReprise(copropriete_id=copro.id, date=data.date, commentaire=data.commentaire or "")
    db.add(etat)
    _remplir(db, etat, data)
    db.flush()
    audit.enregistrer(db, "reprise_etat_cree", user=user, copro_id=copro.id, request=request,
                      detail=f"État au {data.date:%d/%m/%Y}, {len(data.lignes)} ligne(s)")
    db.commit()
    db.refresh(etat)
    return _out(db, copro.id, etat, svc.base(db, copro.id), detail=True)


@router.put("/etats/{etat_id}", response_model=EtatRepriseDetail)
def modifier(etat_id: int, data: EtatRepriseIn, request: Request, db: Session = Depends(get_db),
             user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    etat = _etat(db, etat_id, copro)
    if etat.valide:
        raise HTTPException(422, "Un état validé ne se modifie plus : passez une écriture corrective "
                                 "(appel ou encaissement).")
    svc.controler_saisie(db, copro.id, data.date, data.lignes)
    _doublon(db, copro.id, data, sauf_id=etat.id)
    etat.date = data.date
    etat.commentaire = data.commentaire or ""
    etat.lignes = []
    db.flush()
    _remplir(db, etat, data)
    audit.enregistrer(db, "reprise_etat_modifie", user=user, copro_id=copro.id, request=request,
                      detail=f"État au {data.date:%d/%m/%Y}, {len(data.lignes)} ligne(s)")
    db.commit()
    db.refresh(etat)
    return _out(db, copro.id, etat, svc.base(db, copro.id), detail=True)


def _eur(v) -> str:
    return "non saisi" if v is None else f"{v:.2f} €".replace(".", ",")


@router.put("/etats/{etat_id}/banque", response_model=EtatRepriseDetail)
def modifier_banque(etat_id: int, data: SoldesBanqueIn, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_syndic)):
    """Saisir ou corriger les soldes bancaires d'un état, même validé : ils ne changent ni les soldes
    des copropriétaires ni les appels de reprise (seulement le contrôle bancaire et la trésorerie)."""
    copro = get_or_create_copro(db, user)
    etat = _etat(db, etat_id, copro)
    avant = (etat.solde_banque, etat.solde_banque_fonds)
    etat.solde_banque = data.solde_banque
    etat.solde_banque_fonds = data.solde_banque_fonds
    audit.enregistrer(db, "reprise_banque_modifiee", user=user, copro_id=copro.id, request=request,
                      detail=(f"État au {etat.date:%d/%m/%Y} : syndicat {_eur(avant[0])} → {_eur(data.solde_banque)}, "
                              f"fonds de travaux {_eur(avant[1])} → {_eur(data.solde_banque_fonds)}"))
    db.commit()
    db.refresh(etat)
    return _out(db, copro.id, etat, svc.base(db, copro.id), detail=True)


@router.delete("/etats/{etat_id}")
def supprimer(etat_id: int, request: Request, db: Session = Depends(get_db),
              user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    etat = _etat(db, etat_id, copro)
    if etat.valide:
        raise HTTPException(422, "Un état validé ne se supprime pas.")
    audit.enregistrer(db, "reprise_etat_supprime", user=user, copro_id=copro.id, request=request,
                      detail=f"Brouillon au {etat.date:%d/%m/%Y}")
    db.delete(etat)
    db.commit()
    return {"ok": True}


@router.post("/etats/{etat_id}/valider", response_model=EtatRepriseDetail)
def valider(etat_id: int, request: Request, db: Session = Depends(get_db),
            user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    etat = _etat(db, etat_id, copro)
    role = svc.valider(db, copro.id, etat)
    audit.enregistrer(db, "reprise_etat_valide", user=user, copro_id=copro.id, request=request,
                      detail=f"État au {etat.date:%d/%m/%Y} validé ({role.replace('_', ' ')})")
    db.commit()
    db.refresh(etat)
    return _out(db, copro.id, etat, svc.base(db, copro.id), detail=True)


@router.post("/import", response_model=ImportRepriseOut)
def importer(data: ImportRepriseIn, request: Request, db: Session = Depends(get_db),
             user: User = Depends(require_syndic)):
    """Import CSV (état au 31/12, appels ou paiements) : simulation, puis import en bloc."""
    copro = get_or_create_copro(db, user)
    res = reprise_import.importer(db, copro, data.type, data.contenu, data.simuler, data.date)
    if not data.simuler:
        audit.enregistrer(db, "reprise_import", user=user, copro_id=copro.id, request=request,
                          detail=f"Import CSV {data.type} : {res['resume'].get('lignes', 0)} ligne(s)")
        db.commit()
    else:
        db.rollback()
    return res
