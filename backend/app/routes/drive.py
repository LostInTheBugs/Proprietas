"""Drive de la copropriété : brancher un serveur WebDAV pour y ranger les fichiers.

Réservé au syndic. Règles (voir aussi core/drive.py) :
- on n'enregistre des réglages que si l'essai réussit (dossier créé, fichier témoin écrit, relu, supprimé) ;
- le mot de passe est chiffré en base et ne ressort jamais ; « vide » à l'enregistrement = le garder ;
- tant que des documents sont sur le drive, on ne peut ni le débrancher ni changer son dossier
  (les fichiers deviendraient introuvables) ; l'adresse, l'identifiant et le mot de passe restent
  modifiables (serveur déplacé, mot de passe renouvelé) ;
- branchement et débranchement sont inscrits au journal d'audit ;
- fichiers existants : déplacement vers le drive et rapatriement sur le serveur, par lots
  (services/drive_fichiers.py) ; vérification du drive, fichier renommé retrouvé par son contenu ou
  relié à la main.
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
from app.core.scoping import get_owned
from app.models.copropriete import Copropriete
from app.schemas import DriveIn, DriveRelierIn, DriveSauvegardeIn
from app.services import drive_fichiers, drive_sauvegarde
from app.services.sauvegarde import MDP_MIN

router = APIRouter(prefix="/api/drive", tags=["drive"])


def _sur_le_drive(db: Session, copro) -> int:
    return db.query(Document).filter(Document.copropriete_id == copro.id, Document.emplacement == "drive").count()


def _iso(d):
    return d.isoformat(timespec="minutes") if d else None


def _etat_sauvegarde(copro) -> dict:
    return {"auto": bool(copro.drive_sauvegarde_auto), "mot_de_passe_defini": bool(copro.drive_sauvegarde_password),
            "derniere": _iso(copro.drive_sauvegarde_derniere), "prochaine": _iso(drive_sauvegarde.prochaine(copro)),
            "erreur": copro.drive_sauvegarde_erreur or "", "gardees": drive_sauvegarde.GARDER}


def _dossier_deja_pris(db: Session, copro, url: str, dossier: str):
    """Autre copropriété de l'instance branchée sur le même dossier du même drive (ou l'un dans l'autre) :
    deux copropriétés se supprimeraient leurs fichiers."""
    for autre in db.query(Copropriete).filter(Copropriete.id != copro.id, Copropriete.drive_type == "webdav",
                                              Copropriete.drive_url == url).all():
        a, b = (autre.drive_dossier or "") + "/", dossier + "/"
        if a.startswith(b) or b.startswith(a):
            return autre
    return None


def _etat(db: Session, copro) -> dict:
    return {"autorise": get_settings().drive_actif, "type": copro.drive_type or "", "url": copro.drive_url or "",
            "utilisateur": copro.drive_user or "", "dossier": copro.drive_dossier or "",
            "mot_de_passe_defini": bool(copro.drive_password),
            "documents_sur_le_drive": _sur_le_drive(db, copro),
            "documents_sur_le_serveur": db.query(Document).filter(
                Document.copropriete_id == copro.id, Document.emplacement == "", Document.fichier != "").count(),
            "dossier_propose": drive.dossier_propose(copro.nom),
            "sauvegarde": _etat_sauvegarde(copro)}


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
        copro.drive_sauvegarde_auto = False
        db.commit()
        return _etat(db, copro)
    st = _preparer(data, copro)
    dossier = "/".join(st.dossier)
    if n and dossier != (copro.drive_dossier or ""):
        raise HTTPException(409, f"{n} document(s) sont rangés dans « {copro.drive_dossier} » : "
                                 "le dossier du drive ne peut plus changer.")
    if _dossier_deja_pris(db, copro, st.url, dossier):
        raise HTTPException(409, "Ce dossier du drive est déjà celui d'une autre copropriété de cette instance : "
                                 "choisissez-en un autre.")
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


# ---------------------------------------------------------------- fichiers existants, vérification
def _branche(copro):
    """Le drive de la copropriété ; 409 s'il n'est pas branché, 503 s'il est inutilisable."""
    _autorise()
    from app.routes import documents
    try:
        st = documents._drive(copro)
    except StockageIndisponible as e:
        raise HTTPException(503, f"Drive de la copropriété indisponible : {e}") from e
    if st is None:
        raise HTTPException(409, "Aucun drive n'est branché.")
    return st


def _instance():
    from app.routes import documents
    return documents._stockage()


def _lot(operation, db, copro, action: str, user, request) -> dict:
    try:
        bilan = operation(db, copro, _instance(), _branche(copro))
    except StockageIndisponible as e:
        db.rollback()
        raise HTTPException(503, f"Déplacement interrompu : {e} Les fichiers déjà déplacés le restent.") from e
    if bilan["deplaces"]:
        audit.enregistrer(db, action, user=user, copro_id=copro.id, request=request,
                          detail=f"{bilan['deplaces']} fichier(s), {bilan['restants']} restant(s)")
        db.commit()
    return bilan


@router.post("/deplacer")
def deplacer(request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Déplace vers le drive un LOT de fichiers encore sur le serveur ; à rappeler tant que `restants` > 0."""
    return _lot(drive_fichiers.deplacer_vers_drive, db, get_or_create_copro(db, user), "drive_deplacement", user, request)


@router.post("/rapatrier")
def rapatrier(request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Ramène sur le serveur un LOT de fichiers du drive ; à rappeler tant que `restants` > 0."""
    return _lot(drive_fichiers.rapatrier, db, get_or_create_copro(db, user), "drive_rapatriement", user, request)


@router.get("/verification")
def verification(db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    try:
        return drive_fichiers.verifier(db, copro, _branche(copro))
    except StockageIndisponible as e:
        raise HTTPException(503, f"Drive de la copropriété indisponible : {e}") from e


@router.post("/retrouver")
def retrouver(request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Relie les documents introuvables aux fichiers du drive de même contenu (renommés ou déplacés)."""
    copro = get_or_create_copro(db, user)
    try:
        bilan = drive_fichiers.retrouver(db, copro, _branche(copro))
    except StockageIndisponible as e:
        db.rollback()
        raise HTTPException(503, f"Drive de la copropriété indisponible : {e}") from e
    for r in bilan["relies"]:
        audit.enregistrer(db, "drive_fichier_relie", user=user, copro_id=copro.id, request=request,
                          detail=f"« {r['libelle']} » : {r['ancien']} → {r['nouveau']} (retrouvé par son contenu)")
    db.commit()
    return bilan


@router.post("/relier")
def relier(data: DriveRelierIn, request: Request, db: Session = Depends(get_db),
           user: User = Depends(require_syndic)):
    """Rattache à la main un fichier du drive à un document dont le fichier est introuvable."""
    copro = get_or_create_copro(db, user)
    doc = get_owned(db, Document, data.document_id, copro, label="Document")
    ancien = doc.fichier
    try:
        drive_fichiers.relier(db, copro, _branche(copro), doc, data.chemin)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except StockageIndisponible as e:
        db.rollback()
        raise HTTPException(503, f"Drive de la copropriété indisponible : {e}") from e
    audit.enregistrer(db, "drive_fichier_relie", user=user, copro_id=copro.id, request=request,
                      detail=f"« {doc.libelle} » : {ancien} → {doc.fichier} (choisi par le syndic)")
    db.commit()
    return {"ok": True, "fichier": doc.fichier}


# ---------------------------------------------------------------- sauvegardes sur le drive
@router.put("/sauvegarde")
def regler_sauvegarde(data: DriveSauvegardeIn, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require_syndic)):
    """Mot de passe des sauvegardes déposées sur le drive, et sauvegarde automatique chaque semaine."""
    copro = get_or_create_copro(db, user)
    _branche(copro)
    if data.mot_de_passe:
        if len(data.mot_de_passe) < MDP_MIN:
            raise HTTPException(422, f"Mot de passe trop court ({MDP_MIN} caractères minimum).")
        copro.drive_sauvegarde_password = data.mot_de_passe
    if data.auto and not copro.drive_sauvegarde_password:
        raise HTTPException(422, "Choisissez d'abord le mot de passe des sauvegardes.")
    if bool(copro.drive_sauvegarde_auto) != data.auto or data.mot_de_passe:
        audit.enregistrer(db, "drive_sauvegarde_reglee", user=user, copro_id=copro.id, request=request,
                          detail=("automatique chaque semaine" if data.auto else "à la demande seulement")
                          + (" ; mot de passe changé" if data.mot_de_passe else ""))
    copro.drive_sauvegarde_auto = data.auto
    copro.drive_sauvegarde_tentative = None
    db.commit()
    return _etat(db, copro)


@router.post("/sauvegarde/maintenant")
def sauvegarder_maintenant(request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    st = _branche(copro)
    try:
        bilan = drive_sauvegarde.sauvegarder(db, copro, _instance(), st)
    except StockageIndisponible as e:
        db.rollback()
        raise HTTPException(503, f"Sauvegarde impossible : {e}") from e
    audit.enregistrer(db, "drive_sauvegarde", user=user, copro_id=copro.id, request=request,
                      detail=f"{bilan['fichier']} ({bilan['taille']} octets)")
    db.commit()
    return {**bilan, "etat": _etat(db, copro)}


@router.get("/sauvegardes")
def sauvegardes(db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    try:
        return drive_sauvegarde.lister(_branche(copro))
    except StockageIndisponible as e:
        raise HTTPException(503, f"Drive de la copropriété indisponible : {e}") from e
