"""Relevés bancaires : import et rapprochement, réservés au syndic (services/releves.py)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import audit
from app.core.database import get_db
from app.core.deps import require_syndic
from app.models.mouvement import Mouvement
from app.models.user import User
from app.routes.copro import get_or_create_copro
from app.services import releves

router = APIRouter(prefix="/api/releves", tags=["releves"])


class PointerIn(BaseModel):
    mouvement_ids: List[int]


class IgnorerIn(BaseModel):
    ignoree: bool = True


class CreerIn(BaseModel):
    """Opération créée depuis une ligne du relevé : date, sens et montant viennent de la ligne."""
    libelle: str = ""
    categorie: str = "autre"
    lot_id: Optional[int] = None
    cle_id: Optional[int] = None
    contrat_id: Optional[int] = None
    document_id: Optional[int] = None


@router.get("")
def etat(compte: str = "syndicat", db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    return releves.etat(db, get_or_create_copro(db, user).id, compte)


@router.post("/import")
async def importer(request: Request, fichier: UploadFile = File(...), compte: str = Form("syndicat"),
                   simuler: bool = Form(True), db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """CSV, OFX ou QIF de la banque en ligne ; « simuler » : vérifie sans rien écrire."""
    copro = get_or_create_copro(db, user)
    contenu = await fichier.read(releves.MAX_OCTETS + 1)
    resume = releves.importer(db, copro.id, compte, fichier.filename or "", contenu, simuler)
    if not simuler:
        audit.enregistrer(db, "releve_importe", user=user, copro_id=copro.id, request=request,
                          detail=f"{releves.COMPTES[compte]} : {fichier.filename} — {resume['nouvelles']} opération(s) "
                                 f"nouvelle(s), {resume['deja_importees']} déjà importée(s)")
        db.commit()
    return resume


@router.post("/pointer-surs")
def pointer_surs(request: Request, compte: str = "syndicat", db: Session = Depends(get_db),
                 user: User = Depends(require_syndic)):
    """Valide toutes les propositions sûres du compte."""
    copro = get_or_create_copro(db, user)
    n = releves.pointer_surs(db, copro, compte, user, request)
    db.commit()
    return {"pointees": n}


@router.post("/{ligne_id}/pointer")
def pointer(ligne_id: int, data: PointerIn, request: Request, db: Session = Depends(get_db),
            user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    releves.pointer(db, copro, releves.ligne(db, copro.id, ligne_id), data.mouvement_ids, user, request)
    db.commit()
    return {"ok": True}


@router.post("/{ligne_id}/depointer")
def depointer(ligne_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    releves.depointer(db, copro, releves.ligne(db, copro.id, ligne_id), user, request)
    db.commit()
    return {"ok": True}


@router.post("/{ligne_id}/ignorer")
def ignorer(ligne_id: int, data: IgnorerIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    l = releves.ligne(db, copro.id, ligne_id)
    if data.ignoree and l.mouvements:
        from fastapi import HTTPException
        raise HTTPException(409, "Cette ligne est pointée : dépointez-la avant de la mettre de côté.")
    l.ignoree = data.ignoree
    db.commit()
    return {"ok": True}


@router.post("/{ligne_id}/creer")
def creer(ligne_id: int, data: CreerIn, request: Request, db: Session = Depends(get_db),
          user: User = Depends(require_syndic)):
    """Crée l'opération qui manque (dans l'exercice de l'année de la ligne) et la pointe sur la ligne."""
    from fastapi import HTTPException
    from app.core.money import D, arrondi
    from app.routes.comptes import _controler_mouvement
    from app.schemas import MouvementIn
    from app.services.paiements import _exercice
    copro = get_or_create_copro(db, user)
    l = releves.ligne(db, copro.id, ligne_id)
    if l.ignoree or l.mouvements:
        raise HTTPException(409, "Cette ligne est déjà pointée ou mise de côté.")
    if l.compte == "fonds_travaux" and data.categorie != "fonds_travaux":
        raise HTTPException(422, "Sur le compte du fonds de travaux, l'opération est de catégorie « fonds de travaux ».")
    if l.compte == "syndicat" and data.categorie == "fonds_travaux":
        raise HTTPException(422, "Une opération « fonds de travaux » passe par le compte du fonds de travaux : "
                                 "importez-la avec le relevé de ce compte.")
    entree = MouvementIn(date=l.date, libelle=(data.libelle or "").strip() or l.libelle or "Opération bancaire",
                         type="encaissement" if D(l.montant) > 0 else "depense", categorie=data.categorie,
                         montant=arrondi(abs(D(l.montant))), lot_id=data.lot_id, cle_id=data.cle_id,
                         contrat_id=data.contrat_id, document_id=data.document_id)
    hors_banque = _controler_mouvement(db, copro, entree)
    ex = _exercice(db, copro.id, l.date.year)
    m = Mouvement(copropriete_id=copro.id, exercice_id=ex.id, hors_banque=hors_banque,
                  **entree.model_dump(exclude={"exercice_id", "echeance"}))
    db.add(m)
    db.flush()
    releves.pointer(db, copro, l, [m.id], user, request)
    db.commit()
    return {"ok": True, "mouvement_id": m.id}


@router.delete("/{ligne_id}")
def supprimer(ligne_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    releves.supprimer(db, releves.ligne(db, copro.id, ligne_id))
    db.commit()
    return {"ok": True}
