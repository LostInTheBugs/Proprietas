"""Sauvegarde de la copropriété active : export (archive ZIP) et import (nouvelle copropriété).

Réservé au syndic ; export et import inscrits au journal d'audit. Règles : services/sauvegarde.py.
"""
import os
import tempfile
import unicodedata
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core import audit
from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import require_syndic
from app.core.security import hash_password
from app.models.lot import Lot
from app.models.user import User, UserCopro
from app.routes.copro import get_or_create_copro
from app.schemas import CompteACompleterIn, SauvegardeExportIn
from app.services import sauvegarde as svc

router = APIRouter(prefix="/api/sauvegarde", tags=["sauvegarde"])
BLOC = 1024 * 1024


def _stockage():
    # Même stockage que les documents (les tests et la configuration le remplacent au même endroit).
    from app.routes import documents
    return documents._stockage()


@router.post("/export")
def exporter(data: SauvegardeExportIn, request: Request, db: Session = Depends(get_db),
             user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    fd, chemin = tempfile.mkstemp(suffix=".zip")
    try:
        with os.fdopen(fd, "wb") as sortie:
            manifest = svc.exporter(db, copro, _stockage(), sortie, mot_de_passe=data.mot_de_passe,
                                    donnees_personnelles=data.donnees_personnelles, fichiers=data.fichiers)
    except Exception:
        os.unlink(chemin)
        raise
    options = ", ".join(filter(None, [
        "protégée par mot de passe" if data.mot_de_passe else "sans mot de passe",
        "avec données personnelles" if data.donnees_personnelles else "sans données personnelles",
        "avec les fichiers" if data.fichiers else "sans les fichiers"]))
    audit.enregistrer(db, "sauvegarde_export", user=user, copro_id=copro.id, request=request,
                      detail=f"{manifest['nb_comptes']} compte(s), {manifest['nb_documents']} document(s) ; {options}")
    db.commit()
    ascii_ = unicodedata.normalize("NFKD", copro.nom).encode("ascii", "ignore").decode()
    nom = "".join(c if c.isalnum() else "_" for c in ascii_).strip("_") or "copropriete"
    suffixe = "" if data.donnees_personnelles else "_anonyme"
    return FileResponse(chemin, media_type="application/zip",
                        filename=f"Sauvegarde_{nom}_{date.today().isoformat()}{suffixe}.zip",
                        background=BackgroundTask(os.unlink, chemin))


@router.post("/import")
async def importer(request: Request, fichier: UploadFile = File(...), mot_de_passe: str = Form(""),
                   db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    max_bytes = int(get_settings().import_max_mb * 1024 * 1024)
    taille = 0
    with tempfile.TemporaryFile() as tmp:
        while bloc := await fichier.read(BLOC):
            taille += len(bloc)
            if taille > max_bytes:
                raise HTTPException(413, f"Sauvegarde trop volumineuse (maximum {get_settings().import_max_mb:g} Mo).")
            tmp.write(bloc)
        tmp.seek(0)
        resultat = svc.importer(db, tmp, user, _stockage(), mot_de_passe)
    audit.enregistrer(db, "sauvegarde_import", user=user, copro_id=resultat["copropriete_id"], request=request,
                      detail=(f"« {resultat['nom']} » : {resultat['comptes_crees']} compte(s) créé(s), "
                              f"{resultat['comptes_existants']} existant(s), {resultat['comptes_a_completer']} à compléter, "
                              f"{resultat['documents']} fichier(s)"))
    db.commit()
    return resultat


# ---------------------------------------------------------------- comptes à compléter
def _a_completer(db: Session, copro_id: int):
    return [u for u in (db.query(User).join(UserCopro, UserCopro.user_id == User.id)
                        .filter(UserCopro.copropriete_id == copro_id).order_by(User.id))
            if svc.est_a_completer(u.email)]


@router.get("/comptes-a-completer")
def comptes_a_completer(db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Comptes « Compte N » d'une sauvegarde importée sans données personnelles."""
    copro = get_or_create_copro(db, user)
    resultat = []
    for u in _a_completer(db, copro.id):
        lots = (db.query(Lot.numero).filter(Lot.copropriete_id == copro.id, Lot.proprietaire_id == u.id)
                .order_by(Lot.numero).all())
        resultat.append({"id": u.id, "nom": u.nom, "role": u.role, "lots": [n for (n,) in lots]})
    return resultat


@router.put("/comptes-a-completer/{user_id}")
def completer_compte(user_id: int, data: CompteACompleterIn, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require_syndic)):
    """Remet les informations personnelles d'un compte anonyme. Si l'e-mail est celui d'un compte qui
    existe déjà sur ce serveur, le compte anonyme est fusionné dans ce compte existant."""
    copro = get_or_create_copro(db, user)
    cible = next((u for u in _a_completer(db, copro.id) if u.id == user_id), None)
    if cible is None:
        raise HTTPException(404, "Compte à compléter introuvable.")
    email = data.email.lower().strip()
    if svc.est_a_completer(email):
        raise HTTPException(422, "Saisissez la vraie adresse e-mail de la personne.")
    ancien_nom = cible.nom
    existant = db.query(User).filter(User.email == email).first()
    if existant:
        svc.fusionner_compte(db, cible.id, existant.id, copro.id)
        audit.enregistrer(db, "compte_fusionne", user=user, copro_id=copro.id, request=request,
                          detail=f"{ancien_nom} → compte existant {email}")
        db.commit()
        return {"fusionne": True, "user_id": existant.id}
    cible.email = email
    cible.prenom = data.prenom.strip()
    cible.nom = data.nom.strip()
    cible.telephone = data.telephone.strip()
    cible.adresse = data.adresse.strip()
    if data.password:
        cible.password_hash = hash_password(data.password)
    audit.enregistrer(db, "compte_complete", user=user, copro_id=copro.id, request=request,
                      detail=f"{ancien_nom} → {email}")
    db.commit()
    return {"fusionne": False, "user_id": cible.id}
