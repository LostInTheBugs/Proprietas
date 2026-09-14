from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user, require_syndic
from app.models.user import User, UserCopro
from app.models.copropriete import Copropriete
from app.models.mouvement import Mouvement
from app.schemas import CoproOut, CoproUpdate, TresorerieOut
from app.services.two_factor import politique_defaut

router = APIRouter(prefix="/api/copro", tags=["copro"])


def get_or_create_copro(db: Session, user: User) -> Copropriete:
    """Copropriété active du user :
    1. copro_id porté par le token JWT (après switch) — accès vérifié via la liaison
    2. sinon : copropriété principale (liaison principale, puis première liaison)
    3. sinon : première copro existante, sinon création (premier login)
    """
    token_copro = getattr(user, "_token_data", None) or {}
    cid = token_copro.get("copro_id")
    if cid:
        lien = (db.query(UserCopro)
                .filter(UserCopro.user_id == user.id, UserCopro.copropriete_id == int(cid))
                .first())
        if lien:
            copro = db.query(Copropriete).filter(Copropriete.id == lien.copropriete_id).first()
            if copro:
                return copro
        raise HTTPException(403, "Accès refusé à cette copropriété")
    # Copro principale
    liens = (db.query(UserCopro).filter(UserCopro.user_id == user.id)
             .order_by(UserCopro.principale.desc(), UserCopro.id).all())
    if liens:
        copro = db.query(Copropriete).filter(Copropriete.id == liens[0].copropriete_id).first()
        if copro:
            return copro
    # Aucune liaison : on ne s'attribue JAMAIS une copropriété existante qui n'est
    # pas liée au compte — elle appartient potentiellement à un autre syndic.
    # Premier login (base vide) : création d'une copropriété neuve, liée au compte.
    copro = Copropriete(nom="Ma copropriété", totp_policy=politique_defaut())
    db.add(copro)
    db.commit()
    db.refresh(copro)
    if not user.copropriete_id:
        user.copropriete_id = copro.id
        db.add(UserCopro(user_id=user.id, copropriete_id=copro.id, principale=True))
        db.commit()
    return copro


@router.get("", response_model=CoproOut)
def get_copro(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return get_or_create_copro(db, user)


@router.get("/tresorerie", response_model=TresorerieOut)
def get_tresorerie(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Comptes de la copropriété en LECTURE SEULE (tous rôles) : le compte bancaire
    séparé du syndicat et le compte dédié du fonds de travaux, avec les montants
    portés au crédit selon la comptabilité (encaissements − dépenses des exercices).
    Réservé au syndic : la modification (PUT /api/copro)."""
    copro = get_or_create_copro(db, user)
    mouvements = db.query(Mouvement).filter(Mouvement.copropriete_id == copro.id).all()
    enc = sum(m.montant for m in mouvements if m.type == "encaissement" and m.categorie != "fonds_travaux")
    dep = sum(m.montant for m in mouvements if m.type == "depense" and m.categorie != "fonds_travaux")
    ft_enc = sum(m.montant for m in mouvements if m.type == "encaissement" and m.categorie == "fonds_travaux")
    ft_dep = sum(m.montant for m in mouvements if m.type == "depense" and m.categorie == "fonds_travaux")
    return TresorerieOut(
        compte_bancaire_separe=copro.compte_bancaire_separe or "",
        solde_compte=round(enc - dep, 2),
        fonds_travaux_actif=bool(copro.fonds_travaux_actif),
        fonds_travaux_compte=copro.fonds_travaux_compte or "",
        fonds_travaux_taux_pct=copro.fonds_travaux_taux_pct or 0.0,
        fonds_travaux_solde=round(ft_enc - ft_dep, 2),
    )


@router.put("", response_model=CoproOut)
def update_copro(
    data: CoproUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_syndic),
):
    copro = get_or_create_copro(db, user)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(copro, field, value)
    db.commit()
    db.refresh(copro)
    return copro
