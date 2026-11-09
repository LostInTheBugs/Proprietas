from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request
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
from app.services.regime import regime_copro
from app.core.money import D, arrondi, somme
from app.schemas import (
    ExerciceIn, ExerciceOut, BudgetLineIn, BudgetLineOut,
    AppelIn, AppelOut, AppelLotOut, MouvementIn, MouvementOut, RecapOut, EtatDateLot,
    RegularisationIn, RegularisationOut, ReclasserIn,
)
from app.core import audit
from app.services import regularisation
from app.services.soldes import totaux_lot

router = APIRouter(prefix="/api", tags=["comptes"])


def get_exercice(db: Session, exercice_id: int, copro) -> Exercice:
    return get_owned(db, Exercice, exercice_id, copro, label="Exercice")


# ---------- Exercices ----------
def _exercice_out(ex: Exercice) -> ExerciceOut:
    return ExerciceOut(id=ex.id, annee=ex.annee, cloture=ex.cloture,
                       comptes_approuves_le=ex.comptes_approuves_le,
                       budget_total=arrondi(somme(b.montant for b in ex.budget_lines)))


def _controler_approbation(data: ExerciceIn) -> None:
    """Approbation des comptes par l'AG : exercice clôturé, date passée, pas avant l'exercice."""
    d = data.comptes_approuves_le
    if d is None:
        return
    if not data.cloture:
        raise HTTPException(422, "Les comptes ne peuvent être approuvés que sur un exercice clôturé.")
    if d > date.today():
        raise HTTPException(422, "La date d'approbation des comptes ne peut pas être dans le futur.")
    if d.year < data.annee:
        raise HTTPException(422, f"Les comptes de l'exercice {data.annee} ne peuvent pas avoir été "
                                 f"approuvés avant {data.annee}.")


@router.get("/exercices", response_model=list[ExerciceOut])
def list_exercices(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    copro = get_or_create_copro(db, user)
    exercices = db.query(Exercice).filter(Exercice.copropriete_id == copro.id).order_by(Exercice.annee.desc()).all()
    return [_exercice_out(ex) for ex in exercices]


@router.post("/exercices", response_model=ExerciceOut)
def create_exercice(data: ExerciceIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    if db.query(Exercice).filter(Exercice.copropriete_id == copro.id, Exercice.annee == data.annee).first():
        raise HTTPException(400, "Cet exercice existe déjà")
    _controler_approbation(data)
    ex = Exercice(copropriete_id=copro.id, annee=data.annee, cloture=data.cloture,
                  comptes_approuves_le=data.comptes_approuves_le)
    db.add(ex)
    db.commit()
    db.refresh(ex)
    return _exercice_out(ex)


@router.put("/exercices/{exercice_id}", response_model=ExerciceOut)
def update_exercice(exercice_id: int, data: ExerciceIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    ex = get_exercice(db, exercice_id, copro)
    _controler_approbation(data)
    ex.annee = data.annee
    ex.cloture = data.cloture
    ex.comptes_approuves_le = data.comptes_approuves_le
    db.commit()
    db.refresh(ex)
    return _exercice_out(ex)


@router.delete("/exercices/{exercice_id}")
def delete_exercice(exercice_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    ex = get_exercice(db, exercice_id, copro)
    if any(a.reprise_etat_id is not None for a in ex.appels):
        raise HTTPException(422, "Cet exercice porte un appel de reprise de l'historique : "
                                 "il ne peut pas être supprimé.")
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


@router.put("/budget/{line_id}", response_model=BudgetLineOut)
def update_budget_line(line_id: int, data: BudgetLineIn, db: Session = Depends(get_db),
                       user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    line = get_owned_via(db, BudgetLine, Exercice, line_id, copro, "exercice_id", label="Ligne")
    for champ, valeur in data.model_dump().items():
        setattr(line, champ, valeur)
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
    if appel.reprise_etat_id is not None:
        raise HTTPException(422, "Appel de reprise de l'historique : il se gère depuis l'écran Historique.")
    db.delete(appel)
    db.commit()
    return {"ok": True}


# ---------- Mouvements ----------
# ---------- Régularisation des charges (loi art. 14-1 ; décret art. 6-2, 3°) ----------
@router.get("/exercices/{exercice_id}/regularisation", response_model=RegularisationOut)
def apercu_regularisation(exercice_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Écart par lot entre provisions appelées et charges réelles de l'exercice."""
    ex = get_exercice(db, exercice_id, get_or_create_copro(db, user))
    return regularisation.calcul(db, ex)


@router.post("/exercices/{exercice_id}/regularisation", response_model=RegularisationOut)
def creer_regularisation(exercice_id: int, data: RegularisationIn, request: Request,
                         db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Appel de régularisation (complément ou crédit par lot), une fois les comptes approuvés."""
    copro = get_or_create_copro(db, user)
    ex = get_exercice(db, exercice_id, copro)
    appel = regularisation.creer(db, ex, data.date_echeance)
    audit.enregistrer(db, "regularisation_charges", user=user, copro_id=copro.id, request=request,
                      detail=f"Exercice {ex.annee} — écart total {appel.montant_total:.2f} €, "
                             f"échéance {data.date_echeance:%d/%m/%Y}")
    db.commit()
    return regularisation.calcul(db, ex)


@router.get("/exercices/{exercice_id}/mouvements", response_model=list[MouvementOut])
def list_mouvements(exercice_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    copro = get_or_create_copro(db, user)
    ex = get_exercice(db, exercice_id, copro)
    return db.query(Mouvement).filter(Mouvement.exercice_id == ex.id).order_by(Mouvement.date.desc(), Mouvement.id.desc()).all()


TYPES_MOUVEMENT = ("encaissement", "depense")
CATEGORIES_MOUVEMENT = ("charges", "fonds_travaux", "travaux", "assurance", "energie", "entretien", "autre")


def _controler_mouvement(db: Session, copro, data: MouvementIn) -> None:
    """Type et catégorie connus ; lot et appel rattachés de la même copropriété."""
    if data.type not in TYPES_MOUVEMENT:
        raise HTTPException(422, "Type de mouvement inconnu (encaissement ou dépense).")
    if data.categorie not in CATEGORIES_MOUVEMENT:
        raise HTTPException(422, f"Catégorie inconnue : {data.categorie}.")
    if data.lot_id is not None and not db.query(Lot).filter(
            Lot.id == data.lot_id, Lot.copropriete_id == copro.id).first():
        raise HTTPException(422, "Ce lot n'appartient pas à la copropriété.")
    if data.appel_id is not None and not (db.query(AppelFonds).join(Exercice, AppelFonds.exercice_id == Exercice.id)
                                          .filter(AppelFonds.id == data.appel_id,
                                                  Exercice.copropriete_id == copro.id).first()):
        raise HTTPException(422, "Cet appel de fonds n'appartient pas à la copropriété.")


def _resume_mouvement(m) -> str:
    sens = "+" if m.type == "encaissement" else "−"
    montant = f"{D(m.montant or 0):.2f}".replace(".", ",")
    return (f"{m.date:%d/%m/%Y} « {m.libelle} » {m.categorie} {sens}{montant} €"
            + (f" lot #{m.lot_id}" if m.lot_id else ""))


@router.post("/exercices/{exercice_id}/mouvements", response_model=MouvementOut)
def create_mouvement(exercice_id: int, data: MouvementIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    ex = get_exercice(db, exercice_id, copro)
    _controler_mouvement(db, copro, data)
    m = Mouvement(copropriete_id=ex.copropriete_id, exercice_id=ex.id, **data.model_dump(exclude={"exercice_id"}))
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


@router.put("/mouvements/{mouvement_id}", response_model=MouvementOut)
def update_mouvement(mouvement_id: int, data: MouvementIn, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require_syndic)):
    """Correction d'un mouvement, y compris son exercice ; avant et après au journal d'audit."""
    copro = get_or_create_copro(db, user)
    m = get_owned(db, Mouvement, mouvement_id, copro, label="Mouvement")
    _controler_mouvement(db, copro, data)
    avant = _resume_mouvement(m)
    deplacement = ""
    if data.exercice_id is not None and data.exercice_id != m.exercice_id:
        cible = db.query(Exercice).filter(Exercice.id == data.exercice_id,
                                          Exercice.copropriete_id == copro.id).first()
        if cible is None:
            raise HTTPException(422, "Cet exercice n'appartient pas à la copropriété.")
        source = db.get(Exercice, m.exercice_id)
        if data.type == "depense" or m.type == "depense":
            _controler_regularisation(db, (source, cible))
        deplacement = f", exercice {source.annee} → {cible.annee}"
        m.exercice_id = cible.id
    for champ, valeur in data.model_dump(exclude={"exercice_id"}).items():
        setattr(m, champ, valeur)
    audit.enregistrer(db, "mouvement_modifie", user=user, copro_id=copro.id, request=request,
                      detail=f"Mouvement #{m.id} : {avant} → {_resume_mouvement(m)}{deplacement}")
    db.commit()
    db.refresh(m)
    return m


def _controler_regularisation(db: Session, exercices) -> None:
    """Une dépense ne quitte pas (et n'entre pas dans) un exercice dont les charges sont régularisées."""
    for ex in exercices:
        if regularisation.appel_existant(db, ex) is not None:
            raise HTTPException(422, f"Les charges de l'exercice {ex.annee} sont déjà régularisées : "
                                     "y ajouter ou en retirer une dépense fausserait la régularisation.")


@router.post("/exercices/{exercice_id}/mouvements/reclasser")
def reclasser_mouvements(exercice_id: int, data: ReclasserIn, request: Request, db: Session = Depends(get_db),
                         user: User = Depends(require_syndic)):
    """Déplace vers l'exercice de leur année les mouvements datés d'une autre année que l'exercice."""
    copro = get_or_create_copro(db, user)
    ex = get_exercice(db, exercice_id, copro)
    hors = (db.query(Mouvement).filter(Mouvement.exercice_id == ex.id).order_by(Mouvement.date, Mouvement.id).all())
    hors = [m for m in hors if m.date.year != ex.annee]
    liste = [{"id": m.id, "date": m.date, "libelle": m.libelle, "type": m.type, "montant": float(m.montant or 0),
              "vers": m.date.year} for m in hors]
    if data.simuler or not hors:
        return {"simulation": data.simuler, "mouvements": liste}
    cibles = {}
    for annee in sorted({m.date.year for m in hors}):
        cible = db.query(Exercice).filter(Exercice.copropriete_id == copro.id, Exercice.annee == annee).first()
        if cible is None:
            cible = Exercice(copropriete_id=copro.id, annee=annee, cloture=annee < date.today().year)
            db.add(cible)
            db.flush()
        cibles[annee] = cible
    for m in hors:
        if m.type == "depense":
            _controler_regularisation(db, (ex, cibles[m.date.year]))
    for m in hors:
        m.exercice_id = cibles[m.date.year].id
    par_annee = ", ".join(f"{sum(1 for m in hors if m.date.year == a)} vers {a}" for a in sorted(cibles))
    audit.enregistrer(db, "mouvements_reclasses", user=user, copro_id=copro.id, request=request,
                      detail=f"Exercice {ex.annee} : {len(hors)} mouvement(s) déplacé(s) ({par_annee})")
    db.commit()
    return {"simulation": False, "mouvements": liste}


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

    # Régime « petite copropriété » (art. 41-8, voir country_rules.regime_petite_copro) :
    # calculé avant le garde ci-dessous pour rester renseigné même sans exercice.
    lots = db.query(Lot).filter(Lot.copropriete_id == copro.id).all()
    regime = regime_copro(db, copro.id)
    regime_out = dict(regime_petite_copro=regime["petite"], nb_lots_principaux=regime["nb_lots_principaux"],
                      budget_moyen_3_exercices=regime["budget_moyen"])

    ex = db.query(Exercice).filter(Exercice.copropriete_id == copro.id, Exercice.cloture == False).order_by(Exercice.annee.desc()).first()  # noqa: E712
    if not ex:
        ex = db.query(Exercice).filter(Exercice.copropriete_id == copro.id).order_by(Exercice.annee.desc()).first()
    if not ex:
        return RecapOut(exercice_id=0, annee=0, nb_lots=len(lots), **regime_out)

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
        t = totaux_lot(db, lot)
        lots_out.append(EtatDateLot(
            lot=lot, appels_charges=t["appels_charges"], appels_fonds=t["appels_fonds"],
            encaisse=t["encaisse"], solde=t["solde"],
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
        **regime_out,
    )
