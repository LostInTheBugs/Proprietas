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
  nommés par Proprietas, dans le dossier Sauvegardes) ;
- les syndics sont prévenus par e-mail quand la sauvegarde automatique échoue (au premier échec d'une
  série, pas à chaque nouvel essai), puis quand elle fonctionne de nouveau.
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
from app.models.user import User, UserCopro
from app.services import sauvegarde as svc
from app.services.emailer import EmailError, adresse_publique, config_smtp, envoyer_email

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


def _prevenir(db: Session, copro, sujet: str, corps: str) -> int:
    """E-mail aux syndics de la copropriété (best effort : un échec d'envoi est seulement journalisé)."""
    if config_smtp(copro) is None:
        log.warning("Copropriété %s : pas de réglages d'envoi d'e-mails, syndics non prévenus.", copro.id)
        return 0
    syndics = (db.query(User).join(UserCopro, UserCopro.user_id == User.id)
               .filter(UserCopro.copropriete_id == copro.id, User.role == "syndic", User.is_demo.isnot(True)).all())
    envoyes = 0
    for u in syndics:
        if not u.email or svc.est_a_completer(u.email):
            continue
        try:
            envoyer_email(copro, u.email, sujet, corps)
            envoyes += 1
        except Exception as e:  # noqa: BLE001 — jamais bloquant pour les sauvegardes des autres copropriétés
            log.warning("Copropriété %s : e-mail à %s non envoyé (%s)", copro.id, u.email,
                        e if isinstance(e, EmailError) else type(e).__name__)
    return envoyes


def _corps_echec(copro, detail: str) -> str:
    lignes = [
        "Bonjour,",
        "",
        f"La sauvegarde automatique de « {copro.nom} » sur son drive n'a pas pu être faite.",
        "",
        f"  Raison : {detail}",
        "",
        "Proprietas réessaiera toutes les 6 heures ; vous recevrez un e-mail quand elle fonctionnera de nouveau.",
        "En attendant, la copropriété n'a pas de sauvegarde récente hors du serveur.",
    ]
    if copro.drive_type == "google" and "expiré" in detail:
        lignes += ["",
                   "Avec Google Drive : tant que l'application Google de l'instance est en mode « Test », Google",
                   "retire l'autorisation au bout de 7 jours. Reconnectez Google Drive, et demandez à "
                   "l'administrateur de publier l'application (voir le guide Google Drive).",]
    adresse = adresse_publique(copro)
    lignes += ["", "Pour vérifier ou reconnecter le drive : Réglages → Sauvegarde et stockage"
               + (f" ({adresse.rstrip('/')}/settings?onglet=sauvegarde)." if adresse else "."),
               "", f"— Proprietas — {copro.nom}"]
    return "\n".join(lignes)


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
        en_echec = bool(copro.drive_sauvegarde_erreur)        # déjà en échec : syndics déjà prévenus
        try:
            st = drive.stockage_drive(copro, reglages.drive_reseau_local)
            sauvegarder(db, copro, documents._stockage(), st, maintenant)
            stats["sauvegardes"] += 1
            if en_echec:
                _prevenir(db, copro, f"Proprietas — sauvegarde de « {copro.nom} » rétablie",
                          f"Bonjour,\n\nLa sauvegarde automatique de « {copro.nom} » sur son drive fonctionne de "
                          f"nouveau (sauvegarde du {maintenant:%d/%m/%Y à %H:%M}).\n\n— Proprietas — {copro.nom}")
        except Exception as e:  # noqa: BLE001 — une copropriété en échec n'arrête pas les autres
            db.rollback()
            detail = e.detail if isinstance(e, HTTPException) else str(e)
            copro.drive_sauvegarde_erreur = f"{maintenant:%d/%m/%Y %H:%M} : {detail}"[:300]
            db.commit()
            stats["echecs"] += 1
            log.warning("Sauvegarde sur le drive en échec (copropriété %s) : %s", copro.id, detail)
            if not en_echec:
                _prevenir(db, copro, f"Proprietas — la sauvegarde de « {copro.nom} » a échoué",
                          _corps_echec(copro, detail))
    return stats
