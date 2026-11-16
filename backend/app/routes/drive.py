"""Drive de la copropriété : brancher un serveur WebDAV pour y ranger les fichiers.

Réservé au syndic. Règles (voir aussi core/drive.py) :
- on n'enregistre des réglages que si l'essai réussit (dossier créé, fichier témoin écrit, relu, supprimé) ;
- le mot de passe est chiffré en base et ne ressort jamais ; « vide » à l'enregistrement = le garder ;
- tant que des documents sont sur le drive, on ne peut ni le débrancher ni changer son dossier
  (les fichiers deviendraient introuvables) ; l'adresse, l'identifiant et le mot de passe restent
  modifiables (serveur déplacé, mot de passe renouvelé) ;
- branchement et débranchement sont inscrits au journal d'audit.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core import audit, drive
from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import require_syndic
from app.core.stockage import NomInvalide, StockageIndisponible
from app.models.document import Document
from app.models.user import User
from app.routes.copro import get_or_create_copro
from app.schemas import DriveIn

router = APIRouter(prefix="/api/drive", tags=["drive"])


def _sur_le_drive(db: Session, copro) -> int:
    return db.query(Document).filter(Document.copropriete_id == copro.id, Document.emplacement == "drive").count()


def _etat(db: Session, copro) -> dict:
    return {"autorise": get_settings().drive_actif, "type": copro.drive_type or "", "url": copro.drive_url or "",
            "utilisateur": copro.drive_user or "", "dossier": copro.drive_dossier or "",
            "mot_de_passe_defini": bool(copro.drive_password),
            "documents_sur_le_drive": _sur_le_drive(db, copro),
            "dossier_propose": drive.dossier_propose(copro.nom)}


def _autorise() -> None:
    if not get_settings().drive_actif:
        raise HTTPException(403, "Le drive est désactivé sur cette instance.")


def _preparer(data: DriveIn, copro) -> drive.StockageWebDAV:
    """Le drive décrit par le formulaire (mot de passe enregistré si le champ est vide) ; 422 sinon."""
    if data.type != "webdav":
        raise HTTPException(422, "Type de drive inconnu (seul « webdav » est proposé).")
    dossier = "/".join(drive.assainir(s, "") for s in data.dossier.replace("\\", "/").split("/") if s.strip())
    try:
        url = drive.verifier_adresse(data.url, get_settings().drive_reseau_local)
        if not dossier:
            raise NomInvalide(data.dossier)
        return drive.StockageWebDAV(url, data.utilisateur.strip(),
                                    data.mot_de_passe or (copro.drive_password or ""), dossier)
    except drive.AdresseRefusee as e:
        raise HTTPException(422, str(e)) from e
    except NomInvalide as e:
        raise HTTPException(422, "Dossier du drive invalide (exemple : Proprietas/Ma copropriété).") from e


@router.get("")
def lire(db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    return _etat(db, get_or_create_copro(db, user))


@router.post("/test")
def tester(data: DriveIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Essaie les réglages du formulaire sans rien enregistrer."""
    _autorise()
    st = _preparer(data, get_or_create_copro(db, user))
    try:
        st.verifier_ecriture()
    except StockageIndisponible as e:
        return {"ok": False, "detail": str(e)}
    return {"ok": True, "detail": f"Connexion réussie : le dossier « {'/'.join(st.dossier)} » est prêt."}


@router.put("")
def enregistrer(data: DriveIn, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_syndic)):
    _autorise()
    copro = get_or_create_copro(db, user)
    n = _sur_le_drive(db, copro)
    if data.type == "":
        if n:
            raise HTTPException(409, f"{n} document(s) sont sur le drive : il ne peut pas être débranché.")
        if copro.drive_type:
            audit.enregistrer(db, "drive_debranche", user=user, copro_id=copro.id, request=request,
                              detail=copro.drive_url or "")
        copro.drive_type = copro.drive_url = copro.drive_user = copro.drive_password = copro.drive_dossier = ""
        db.commit()
        return _etat(db, copro)
    st = _preparer(data, copro)
    dossier = "/".join(st.dossier)
    if n and dossier != (copro.drive_dossier or ""):
        raise HTTPException(409, f"{n} document(s) sont rangés dans « {copro.drive_dossier} » : "
                                 "le dossier du drive ne peut plus changer.")
    try:
        st.verifier_ecriture()
    except StockageIndisponible as e:
        raise HTTPException(422, f"Réglages non enregistrés : {e}") from e
    copro.drive_type, copro.drive_url, copro.drive_user, copro.drive_dossier = "webdav", st.url, data.utilisateur.strip(), dossier
    if data.mot_de_passe:
        copro.drive_password = data.mot_de_passe
    audit.enregistrer(db, "drive_branche", user=user, copro_id=copro.id, request=request,
                      detail=f"{st.url} — dossier « {dossier} »")
    db.commit()
    return _etat(db, copro)
