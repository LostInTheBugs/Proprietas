"""Sauvegarde de la copropriété déposée sur son drive, chaque semaine ou à la demande.

    <dossier du drive>/Sauvegardes/Sauvegarde 2026-11-17 03h30.zip

Contenu : toutes les données, données personnelles comprises, et les fichiers encore sur le serveur ;
les fichiers déjà rangés sur le drive n'y sont pas recopiés (leurs fiches gardent leur chemin :
`services/sauvegarde.exporter(liens_drive=True)`). Le drive contient donc tout ce qu'il faut pour
repartir sur un autre serveur : importer l'archive, puis rebrancher le drive.

Règles :
- l'archive est TOUJOURS chiffrée (AES-256) par un mot de passe choisi par le syndic, gardé chiffré en
  base ; il n'est pas dans la sauvegarde : sans lui, elle est illisible ;
- automatique : une sauvegarde quand la dernière réussie a 7 jours ; après un échec, nouvel essai au
  plus toutes les 6 heures ; la raison de l'échec est gardée pour l'écran ;
- les 8 sauvegardes les plus récentes sont gardées, les plus anciennes supprimées (seuls les fichiers
  nommés par Proprietas, dans le dossier Sauvegardes).
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core import drive
from app.core.config import get_settings
from app.core.stockage import StockageIndisponible
from app.models.copropriete import Copropriete
from app.services import sauvegarde as svc

DOSSIER = "Sauvegardes"
INTERVALLE = timedelta(days=7)
REPRISE = timedelta(hours=6)
GARDER = 8
NOM = re.compile(r"^Sauvegarde \d{4}-\d{2}-\d{2} \d{2}h\d{2}( \(\d+\))?\.zip$")
log = logging.getLogger("uvicorn.error")


def lister(st_drive) -> list[dict]:
    """Sauvegardes présentes sur le drive, la plus récente d'abord."""
    arbre = st_drive.lister_arbre()
    noms = sorted((c for c in arbre if c.startswith(DOSSIER + "/") and NOM.match(c[len(DOSSIER) + 1:])), reverse=True)
    return [{"fichier": c, "taille": arbre[c]} for c in noms]


def sauvegarder(db: Session, copro, instance, st_drive, maintenant: datetime | None = None) -> dict:
    """Dépose une sauvegarde sur le drive et supprime les plus anciennes. HTTPException / StockageIndisponible."""
    maintenant = maintenant or datetime.now()
    if not copro.drive_sauvegarde_password:
        raise HTTPException(422, "Choisissez d'abord le mot de passe des sauvegardes.")
    fd, chemin = tempfile.mkstemp(suffix=".zip")
    try:
        with os.fdopen(fd, "wb") as sortie:
            manifest = svc.exporter(db, copro, instance, sortie, mot_de_passe=copro.drive_sauvegarde_password,
                                    donnees_personnelles=True, fichiers=True, liens_drive=True)
        nom = st_drive.nom_libre(DOSSIER, f"Sauvegarde {maintenant:%Y-%m-%d %Hh%M}.zip")
        taille = os.path.getsize(chemin)
        with open(chemin, "rb") as flux:
            st_drive.enregistrer(nom, flux)
        if st_drive.taille(nom) != taille:
            raise StockageIndisponible("Sauvegarde incomplète sur le drive.")
    finally:
        os.unlink(chemin)
    copro.drive_sauvegarde_derniere, copro.drive_sauvegarde_erreur = maintenant, ""
    db.commit()
    supprimees = 0
    try:
        for ancienne in lister(st_drive)[GARDER:]:
            st_drive.supprimer(ancienne["fichier"])
            supprimees += 1
    except StockageIndisponible:
        pass                    # le ménage se refera à la prochaine sauvegarde
    return {"fichier": nom, "taille": taille, "documents": manifest["nb_documents"], "supprimees": supprimees}


def prochaine(copro) -> datetime | None:
    """Date de la prochaine sauvegarde automatique (None si elle n'est pas activée)."""
    if not copro.drive_sauvegarde_auto or copro.drive_type not in drive.TYPES:
        return None
    return copro.drive_sauvegarde_derniere + INTERVALLE if copro.drive_sauvegarde_derniere else datetime.now()


def run_sauvegardes_drive(db: Session, maintenant: datetime | None = None) -> dict:
    """Passage du planificateur : sauvegarde les copropriétés dont c'est le tour."""
    maintenant = maintenant or datetime.now()
    stats = {"sauvegardes": 0, "echecs": 0}
    reglages = get_settings()
    if not reglages.drive_actif:
        return stats
    from app.routes import documents      # stockage de l'instance, au même endroit que les documents
    copros = db.query(Copropriete).filter(Copropriete.drive_type.in_(drive.TYPES),
                                          Copropriete.drive_sauvegarde_auto.is_(True)).all()
    for copro in copros:
        if copro.drive_sauvegarde_derniere and maintenant - copro.drive_sauvegarde_derniere < INTERVALLE:
            continue
        if copro.drive_sauvegarde_tentative and maintenant - copro.drive_sauvegarde_tentative < REPRISE:
            continue
        copro.drive_sauvegarde_tentative = maintenant
        db.commit()
        try:
            st = drive.stockage_drive(copro, reglages.drive_reseau_local)
            sauvegarder(db, copro, documents._stockage(), st, maintenant)
            stats["sauvegardes"] += 1
        except Exception as e:  # noqa: BLE001 — une copropriété en échec n'arrête pas les autres
            db.rollback()
            detail = e.detail if isinstance(e, HTTPException) else str(e)
            copro.drive_sauvegarde_erreur = f"{maintenant:%d/%m/%Y %H:%M} : {detail}"[:300]
            db.commit()
            stats["echecs"] += 1
            log.warning("Sauvegarde sur le drive en échec (copropriété %s) : %s", copro.id, detail)
    return stats
