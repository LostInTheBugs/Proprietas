from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user, require_syndic
from app.models.user import User
from app.models.contrat import Contrat
from app.models.contact import Contact
from app.models.mouvement import Mouvement
from app.core.money import D, arrondi, somme
from app.core.scoping import get_owned
from app.routes.copro import get_or_create_copro
from app.schemas import ContratIn, ContratOut

router = APIRouter(prefix="/api/contrats", tags=["contrats"])

_TYPES = {
    "energie": "Énergie (électricité, gaz)",
    "assurance": "Assurance",
    "entretien": "Entretien / maintenance",
    "telecom": "Télécom / internet",
    "nettoyage": "Nettoyage",
    "securite": "Sécurité / alarme",
    "eau": "Eau / assainissement",
    "autres": "Autres",
}

_PERIODES = {
    "mensuel": "Mensuel",
    "trimestriel": "Trimestriel",
    "annuel": "Annuel",
    "ponctuel": "Ponctuel",
}

_SEUIL_ALERTE_JOURS = 60


def _statut_contrat(c: Contrat) -> tuple[str, int | None]:
    """Statut calculé : actif / expire_bientot (≤ 60 j) / expire + jours restants."""
    if not c.date_fin:
        return "actif", None
    try:
        fin = datetime.strptime(c.date_fin, "%Y-%m-%d").date()
    except ValueError:
        return "actif", None
    jours = (fin - date.today()).days
    if jours < 0:
        return "expire", jours
    if jours <= _SEUIL_ALERTE_JOURS:
        return "expire_bientot", jours
    return "actif", jours


def _out(db: Session, c: Contrat) -> ContratOut:
    statut, jours = _statut_contrat(c)
    o = ContratOut.model_validate(c)
    o.contact_nom = c.contact.nom if c.contact else ""
    o.statut = statut
    o.jours_restants = jours
    # Mouvements rattachés : nombre, et total des dépenses de l'année en cours.
    mouvements = db.query(Mouvement).filter(Mouvement.contrat_id == c.id).all()
    o.nb_mouvements = len(mouvements)
    o.depenses_annee = float(arrondi(somme(D(m.montant or 0) for m in mouvements
                                           if m.type == "depense" and m.date and m.date.year == date.today().year)))
    return o


@router.get("", response_model=list[ContratOut])
def liste(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    copro = get_or_create_copro(db, user)
    contrats = db.query(Contrat).filter(Contrat.copropriete_id == copro.id).all()
    # Les plus urgents d'abord : expirés, puis échéances proches, puis actifs
    def cle(c):
        statut, jours = _statut_contrat(c)
        return (0 if statut == "expire" else 1 if statut == "expire_bientot" else 2, jours if jours is not None else 9999, c.id)
    return [_out(db, c) for c in sorted(contrats, key=cle)]


@router.post("", response_model=ContratOut)
def creer(data: ContratIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    c = Contrat(copropriete_id=copro.id, **data.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return _out(db, c)


@router.put("/{contrat_id}", response_model=ContratOut)
def modifier(contrat_id: int, data: ContratIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    c = get_owned(db, Contrat, contrat_id, copro, label="Contrat")
    for k, v in data.model_dump().items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return _out(db, c)


@router.delete("/{contrat_id}")
def supprimer(contrat_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    c = get_owned(db, Contrat, contrat_id, copro, label="Contrat")
    # Les mouvements rattachés restent, déliés.
    db.query(Mouvement).filter(Mouvement.contrat_id == c.id).update({Mouvement.contrat_id: None},
                                                                    synchronize_session=False)
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.get("/types")
def types():
    return _TYPES


@router.get("/periodes")
def periodes():
    return _PERIODES
