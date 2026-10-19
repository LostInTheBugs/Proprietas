from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user, require_syndic
from app.models.user import User
from app.models.lot import Lot
from app.models.exercice import Exercice, BudgetLine
from app.models.appel import AppelFonds, AppelLot
from app.models.mouvement import Mouvement
from app.core.scoping import get_owned, get_owned_via
from app.routes.copro import get_or_create_copro
from app.services.country_rules import repartir_par_tantiemes
from app.core.money import D, arrondi, somme
from app.schemas import (
    ExerciceIn, ExerciceOut, BudgetLineIn, BudgetLineOut,
    AppelIn, AppelOut, AppelLotOut, MouvementIn, MouvementOut, RecapOut, EtatDateLot,
)

router = APIRouter(prefix="/api", tags=["comptes"])


def get_exercice(db: Session, exercice_id: int, copro) -> Exercice:
    return get_owned(db, Exercice, exercice_id, copro, label="Exercice")


# ---------- Exercices ----------
@router.get("/exercices", response_model=list[ExerciceOut])
def list_exercices(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    copro = get_or_create_copro(db, user)
    exercices = db.query(Exercice).filter(Exercice.copropriete_id == copro.id).order_by(Exercice.annee.desc()).all()
    out = []
    for ex in exercices:
        budget = somme(b.montant for b in ex.budget_lines)
        out.append(ExerciceOut(id=ex.id, annee=ex.annee, cloture=ex.cloture, budget_total=arrondi(budget)))
    return out


@router.post("/exercices", response_model=ExerciceOut)
def create_exercice(data: ExerciceIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    if db.query(Exercice).filter(Exercice.copropriete_id == copro.id, Exercice.annee == data.annee).first():
        raise HTTPException(400, "Cet exercice existe déjà")
    ex = Exercice(copropriete_id=copro.id, annee=data.annee, cloture=data.cloture)
    db.add(ex)
    db.commit()
    db.refresh(ex)
    return ExerciceOut(id=ex.id, annee=ex.annee, cloture=ex.cloture, budget_total=D(0))


@router.put("/exercices/{exercice_id}", response_model=ExerciceOut)
def update_exercice(exercice_id: int, data: ExerciceIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    ex = get_exercice(db, exercice_id, copro)
    ex.annee = data.annee
    ex.cloture = data.cloture
    db.commit()
    db.refresh(ex)
    budget = somme(b.montant for b in ex.budget_lines)
    return ExerciceOut(id=ex.id, annee=ex.annee, cloture=ex.cloture, budget_total=arrondi(budget))


@router.delete("/exercices/{exercice_id}")
def delete_exercice(exercice_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    ex = get_exercice(db, exercice_id, copro)
    db.delete(ex)
    db.commit()
    return {"ok": True}


# ---------- Budget ----------
@router.get("/exercices/{exercice_id}/budget", response_model=list[BudgetLineOut])
def get_budget(exercice_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    copro = get_or_create_copro(db, user)
    ex = get_exercice(db, exercice_id, copro)
    return ex.budget_lines


@router.post("/exercices/{exercice_id}/budget", response_model=BudgetLineOut)
def add_budget_line(exercice_id: int, data: BudgetLineIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    ex = get_exercice(db, exercice_id, copro)
    line = BudgetLine(exercice_id=ex.id, **data.model_dump())
    db.add(line)
    db.commit()
    db.refresh(line)
    return line


@router.delete("/budget/{line_id}")
def delete_budget_line(line_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    line = get_owned_via(db, BudgetLine, Exercice, line_id, copro, "exercice_id", label="Ligne")
    db.delete(line)
    db.commit()
    return {"ok": True}


# ---------- Appels de fonds ----------
@router.get("/exercices/{exercice_id}/appels", response_model=list[AppelOut])
def list_appels(exercice_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    copro = get_or_create_copro(db, user)
    ex = get_exercice(db, exercice_id, copro)
    appels = db.query(AppelFonds).filter(AppelFonds.exercice_id == ex.id).order_by(AppelFonds.date_emission).all()
    out = []
    for a in appels:
        parts = []
        for p in a.parts:
            lot = db.query(Lot).filter(Lot.id == p.lot_id).first()
            parts.append(AppelLotOut(
                id=p.id, lot_id=p.lot_id,
                lot_numero=lot.numero if lot else f"#{p.lot_id}",
                montant_charges=p.montant_charges,
                montant_fonds_travaux=p.montant_fonds_travaux,
            ))
        out.append(AppelOut(
            id=a.id, exercice_id=a.exercice_id, libelle=a.libelle,
            date_emission=a.date_emission, date_echeance=a.date_echeance,
            montant_total=a.montant_total, inclut_fonds_travaux=a.inclut_fonds_travaux,
            fonds_travaux_montant=a.fonds_travaux_montant, parts=parts,
        ))
    return out


@router.post("/exercices/{exercice_id}/appels", response_model=AppelOut)
def create_appel(exercice_id: int, data: AppelIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    ex = get_exercice(db, exercice_id, copro)
    lots = db.query(Lot).filter(Lot.copropriete_id == ex.copropriete_id).all()
    if not lots:
        raise HTTPException(400, "Créez d'abord des lots avec des tantièmes")

    appel = AppelFonds(
        exercice_id=ex.id,
        libelle=data.libelle,
        date_emission=data.date_emission,
        date_echeance=data.date_echeance,
        montant_total=data.montant_total,
        inclut_fonds_travaux=data.inclut_fonds_travaux and copro.fonds_travaux_actif,
        fonds_travaux_montant=D(0),
    )
    db.add(appel)
    db.flush()

    taux = copro.fonds_travaux_taux_pct if appel.inclut_fonds_travaux else D(0)
    parts = repartir_par_tantiemes(data.montant_total, lots, taux)
    for p in parts:
        db.add(AppelLot(
            appel_id=appel.id,
            lot_id=p["lot"].id,
            montant_charges=p["montant_charges"],
            montant_fonds_travaux=p.get("montant_fonds_travaux", D(0)),
        ))
    appel.fonds_travaux_montant = somme(p.get("montant_fonds_travaux", D(0)) for p in parts)
    db.commit()
    db.refresh(appel)
    return _appel_out(db, appel)


def _appel_out(db: Session, a: AppelFonds) -> AppelOut:
    parts = []
    for p in a.parts:
        lot = db.query(Lot).filter(Lot.id == p.lot_id).first()
        parts.append(AppelLotOut(
            id=p.id, lot_id=p.lot_id,
            lot_numero=lot.numero if lot else f"#{p.lot_id}",
            montant_charges=p.montant_charges,
            montant_fonds_travaux=p.montant_fonds_travaux,
        ))
    return AppelOut(
        id=a.id, exercice_id=a.exercice_id, libelle=a.libelle,
        date_emission=a.date_emission, date_echeance=a.date_echeance,
        montant_total=a.montant_total, inclut_fonds_travaux=a.inclut_fonds_travaux,
        fonds_travaux_montant=a.fonds_travaux_montant, parts=parts,
    )


@router.delete("/appels/{appel_id}")
def delete_appel(appel_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    appel = get_owned_via(db, AppelFonds, Exercice, appel_id, copro, "exercice_id", label="Appel")
    db.delete(appel)
    db.commit()
    return {"ok": True}


# ---------- Mouvements ----------
@router.get("/exercices/{exercice_id}/mouvements", response_model=list[MouvementOut])
def list_mouvements(exercice_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    copro = get_or_create_copro(db, user)
    ex = get_exercice(db, exercice_id, copro)
    return db.query(Mouvement).filter(Mouvement.exercice_id == ex.id).order_by(Mouvement.date.desc(), Mouvement.id.desc()).all()


@router.post("/exercices/{exercice_id}/mouvements", response_model=MouvementOut)
def create_mouvement(exercice_id: int, data: MouvementIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    ex = get_exercice(db, exercice_id, copro)
    m = Mouvement(copropriete_id=ex.copropriete_id, exercice_id=ex.id, **data.model_dump())
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


@router.delete("/mouvements/{mouvement_id}")
def delete_mouvement(mouvement_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    m = get_owned(db, Mouvement, mouvement_id, copro, label="Mouvement")
    db.delete(m)
    db.commit()
    return {"ok": True}


# ---------- Récapitulatif (dashboard) ----------
@router.get("/recap", response_model=RecapOut)
def recap(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    copro = get_or_create_copro(db, user)

    # Régime « petite copropriété » (art. 41-8) : ≤ 5 lots ou budget prévisionnel
    # moyen < 15 000 €/an sur les 3 derniers exercices — calculé avant le garde
    # ci-dessous pour rester renseigné même sans exercice
    lots = db.query(Lot).filter(Lot.copropriete_id == copro.id).all()
    exercices = (db.query(Exercice).filter(Exercice.copropriete_id == copro.id)
                 .order_by(Exercice.annee.desc()).limit(3).all())
    budgets = [somme(b.montant for b in e.budget_lines) for e in exercices]
    budget_moyen = (somme(budgets) / len(budgets)) if budgets else D(0)
    regime_petite = len(lots) <= 5 or budget_moyen < 15000

    ex = db.query(Exercice).filter(Exercice.copropriete_id == copro.id, Exercice.cloture == False).order_by(Exercice.annee.desc()).first()  # noqa: E712
    if not ex:
        ex = db.query(Exercice).filter(Exercice.copropriete_id == copro.id).order_by(Exercice.annee.desc()).first()
    if not ex:
        return RecapOut(exercice_id=0, annee=0, nb_lots=len(lots), regime_petite_copro=regime_petite)

    budget = somme(b.montant for b in ex.budget_lines)
    mouvements = db.query(Mouvement).filter(Mouvement.exercice_id == ex.id).all()
    encaisse = somme(m.montant for m in mouvements if m.type == "encaissement")
    depense = somme(m.montant for m in mouvements if m.type == "depense")
    ft_encaisse = somme(m.montant for m in mouvements if m.type == "encaissement" and m.categorie == "fonds_travaux")
    appels_en_cours = db.query(AppelFonds).filter(
        AppelFonds.exercice_id == ex.id,
        AppelFonds.date_echeance.isnot(None),
    ).count()

    lots_out = []
    for lot in lots:
        appels_c = somme(a.montant_charges for a in db.query(AppelLot).filter(AppelLot.lot_id == lot.id).all())
        appels_f = somme(a.montant_fonds_travaux for a in db.query(AppelLot).filter(AppelLot.lot_id == lot.id).all())
        enc = somme(m.montant for m in db.query(Mouvement).filter(
            Mouvement.lot_id == lot.id, Mouvement.type == "encaissement").all())
        lots_out.append(EtatDateLot(
            lot=lot, appels_charges=arrondi(appels_c), appels_fonds=arrondi(appels_f),
            encaisse=arrondi(enc), solde=arrondi(appels_c + appels_f - enc),
        ))

    return RecapOut(
        exercice_id=ex.id, annee=ex.annee,
        budget_previsionnel=arrondi(budget),
        encaisse=arrondi(encaisse), depense=arrondi(depense),
        solde_caisse=arrondi(encaisse - depense),
        fonds_travaux_encaisse=arrondi(ft_encaisse),
        appels_en_cours=appels_en_cours,
        lots=lots_out,
        nb_lots=len(lots),
        regime_petite_copro=regime_petite,
    )
