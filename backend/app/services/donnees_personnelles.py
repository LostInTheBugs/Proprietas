"""Droit d'accès (RGPD, art. 15) : toutes les données d'un compte, et seulement les siennes.

Profil, copropriétés, lots détenus, décompte de ces lots, votes exprimés pour ces lots,
convocations et relances reçues, actes de recouvrement le concernant, journal de ses
actions. Jamais de secret (hash du mot de passe, secret 2FA, codes de secours).
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.version import VERSION
from app.models.ag import AG, Resolution, Vote
from app.models.audit import AuditLog
from app.models.copropriete import Copropriete
from app.models.invitation import Invitation
from app.models.lot import Lot
from app.models.recouvrement import ActeRecouvrement
from app.models.relance import Relance
from app.models.user import User, UserCopro
from app.services.recouvrement import appels_lot


def donnees_personnelles(db: Session, user: User) -> dict:
    copros = (db.query(Copropriete).join(UserCopro, UserCopro.copropriete_id == Copropriete.id)
              .filter(UserCopro.user_id == user.id).all())
    lots = db.query(Lot).filter(Lot.proprietaire_id == user.id).order_by(Lot.copropriete_id, Lot.id).all()
    noms = {c.id: c.nom for c in copros}
    for lot in lots:
        if lot.copropriete_id not in noms:
            c = db.get(Copropriete, lot.copropriete_id)
            noms[lot.copropriete_id] = c.nom if c else ""

    decomptes = []
    for lot in lots:
        copro = db.get(Copropriete, lot.copropriete_id)
        for l in appels_lot(db, copro, lot):
            decomptes.append({"lot": lot.numero, "copropriete": noms.get(lot.copropriete_id, ""),
                              "exercice": l["exercice"], "libelle": l["libelle"], "echeance": l["echeance"],
                              "montant": l["montant"], "restant_du": l["restant_du"]})

    ids_lots = [l.id for l in lots]
    votes = []
    if ids_lots:
        for v, r, ag, lot in (db.query(Vote, Resolution, AG, Lot)
                              .join(Resolution, Vote.resolution_id == Resolution.id)
                              .join(AG, Resolution.ag_id == AG.id)
                              .join(Lot, Vote.lot_id == Lot.id)
                              .filter(Vote.lot_id.in_(ids_lots)).all()):
            votes.append({"ag": ag.date, "resolution": r.numero, "libelle": r.libelle,
                          "lot": lot.numero, "voix": v.voix})

    return {
        "genere_le": datetime.now(),
        "application": f"Proprietas {VERSION}",
        "profil": {
            "email": user.email, "prenom": user.prenom, "nom": user.nom,
            "adresse": user.adresse, "telephone": user.telephone, "role": user.role,
            "double_authentification": bool(user.totp_enabled), "theme": user.theme,
            "derniere_connexion": user.last_login_at, "derniere_ip": user.last_login_ip,
            "dernier_navigateur": user.last_login_ua,
        },
        "coproprietes": [{"nom": c.nom, "adresse": c.adresse, "code_postal": c.code_postal,
                          "ville": c.ville} for c in copros],
        "lots": [{"copropriete": noms.get(l.copropriete_id, ""), "numero": l.numero,
                  "designation": l.designation, "type": l.type, "tantiemes": l.tantiemes,
                  "surface_m2": l.surface_m2, "statut_occupation": l.statut_occupation} for l in lots],
        "decomptes": decomptes,
        "votes": votes,
        "convocations": [{"date_envoi": i.date_envoi, "statut": i.statut, "message": i.message}
                         for i in db.query(Invitation).filter(Invitation.personne_id == user.id).all()],
        "relances": [{"date_envoi": r.date_envoi, "statut": r.statut, "montant_du": r.montant_du,
                      "message": r.message}
                     for r in db.query(Relance).filter(Relance.personne_id == user.id).all()],
        "actes_recouvrement": [{"type": a.type, "date_envoi": a.date_envoi, "mode_envoi": a.mode_envoi,
                                "date_reception": a.date_reception, "montant": a.montant,
                                "libelle": a.libelle}
                               for a in db.query(ActeRecouvrement)
                               .filter(ActeRecouvrement.personne_id == user.id).all()],
        "journal": [{"date": a.created_at, "action": a.action, "ip": a.ip}
                    for a in db.query(AuditLog).filter(AuditLog.user_id == user.id)
                    .order_by(AuditLog.created_at).all()],
    }
