"""Factures à payer (demande de Fred, 20/11/2026, après les impayés EDF et assurance de l'immeuble).

Une dépense peut être saisie « à payer », avec une échéance, dès que la facture arrive :
- elle compte dans les charges de l'exercice (date de la facture), pas encore dans la banque ;
- « Marquer payée » : par le compte de la copropriété (`paye_le`, date du virement, retenue par la banque),
  ou par une personne de sa poche (elle devient une avance, services/avances.py) ;
- tableau de bord du syndic : les factures à payer, en retard en rouge ;
- e-mail aux syndics 7 jours avant l'échéance, puis le lendemain de l'échéance si elle n'est toujours pas
  réglée (un seul e-mail de chaque sorte par facture, regroupé par copropriété).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal as D

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core import audit
from app.core.money import arrondi
from app.models.copropriete import Copropriete
from app.models.mouvement import Mouvement

log = logging.getLogger("uvicorn.error")
JOURS_AVANT = 7


def date_banque(m: Mouvement) -> date:
    """Date à laquelle le mouvement passe en banque (paiement différé : la date du paiement)."""
    return m.paye_le or m.date


def controler(data) -> None:
    """Une facture à payer est une dépense ordinaire, réglée plus tard ; 422 sinon."""
    if not getattr(data, "a_payer", False):
        return
    if data.type != "depense" or data.categorie == "avance" or data.avance_par_id is not None:
        raise HTTPException(422, "« À payer » : seulement pour une dépense qui n'est pas encore réglée (ni un "
                                 "remboursement, ni une avance déjà payée par quelqu'un).")


def en_retard(m: Mouvement, aujourd_hui: date | None = None) -> bool:
    return bool(m.a_payer and m.echeance and m.echeance < (aujourd_hui or date.today()))


def liste(db: Session, copro_id: int) -> list[dict]:
    """Factures à payer de la copropriété, la plus urgente d'abord (sans échéance : à la fin)."""
    rows = (db.query(Mouvement).filter(Mouvement.copropriete_id == copro_id, Mouvement.a_payer.is_(True)).all())
    rows.sort(key=lambda m: (m.echeance is None, m.echeance or date.max, m.date, m.id))
    return [{"id": m.id, "date": m.date, "libelle": m.libelle, "categorie": m.categorie,
             "montant": arrondi(D(m.montant or 0)), "echeance": m.echeance, "en_retard": en_retard(m),
             "exercice_id": m.exercice_id, "document_id": m.document_id, "contrat_id": m.contrat_id}
            for m in rows]


def payer(db: Session, copro, m: Mouvement, jour: date, avance_par_id: int | None, user, request) -> Mouvement:
    """Marque payée une facture à payer : par la copropriété (date du paiement), ou par une personne (avance)."""
    from app.services import avances
    if not m.a_payer:
        raise HTTPException(409, "Cette dépense n'est pas « à payer ».")
    if avance_par_id is not None:
        from types import SimpleNamespace
        avance = SimpleNamespace(type=m.type, categorie=m.categorie, document_id=m.document_id, lot_id=m.lot_id,
                                 montant=m.montant, avance_par_id=avance_par_id)   # contrôle d'une dépense « payée par »
        m.hors_banque = avances.controler(db, copro, avance, m)
        m.a_payer = False
        m.avance_par_id = avance_par_id
        detail = f"payée par {avances._nom(m.avance_par) if m.avance_par else '?'} (avance)"
    else:
        if jour < m.date:
            raise HTTPException(422, "La date du paiement ne peut pas précéder celle de la facture.")
        m.a_payer, m.paye_le = False, jour
        detail = f"payée le {jour:%d/%m/%Y}"
    audit.enregistrer(db, "facture_payee", user=user, copro_id=copro.id, request=request,
                      detail=f"« {m.libelle} » ({arrondi(D(m.montant or 0))} €) {detail}")
    return m


def _corps(copro, lignes: list[Mouvement], retard: bool) -> str:
    entete = (f"Ces factures de « {copro.nom} » ne sont toujours pas réglées alors que leur échéance est passée :"
              if retard else f"Ces factures de « {copro.nom} » arrivent à échéance dans les {JOURS_AVANT} jours :")
    corps = ["Bonjour,", "", entete, ""]
    for m in lignes:
        corps.append(f"  • {m.libelle} — {arrondi(D(m.montant or 0))} € — échéance le {m.echeance:%d/%m/%Y}")
    corps += ["", "Réglez-les, puis « Marquer payée » dans Proprietas (tableau de bord). Si quelqu'un les a payées de "
                  "sa poche, choisissez-le : la dépense devient une avance à lui rembourser.",
              "", "— Proprietas"]
    return "\n".join(corps)


def run_rappels(db: Session, maintenant: datetime | None = None) -> dict:
    """Rappels aux syndics (planificateur) : 7 jours avant l'échéance, puis une fois l'échéance passée."""
    from app.services.drive_sauvegarde import _prevenir
    maintenant = maintenant or datetime.now()
    jour = maintenant.date()
    stats = {"avant": 0, "retard": 0}
    factures = (db.query(Mouvement).filter(Mouvement.a_payer.is_(True), Mouvement.echeance.isnot(None)).all())
    par_copro: dict[int, dict[str, list]] = {}
    for m in factures:
        if m.echeance < jour and m.rappel_retard_le is None:
            par_copro.setdefault(m.copropriete_id, {"avant": [], "retard": []})["retard"].append(m)
        elif m.echeance >= jour and m.echeance - timedelta(days=JOURS_AVANT) <= jour and m.rappel_avant_le is None:
            par_copro.setdefault(m.copropriete_id, {"avant": [], "retard": []})["avant"].append(m)
    for copro_id, sortes in par_copro.items():
        copro = db.get(Copropriete, copro_id)
        for sorte, lignes in sortes.items():
            if not lignes:
                continue
            sujet = (f"Proprietas — {copro.nom} : facture(s) en retard de paiement" if sorte == "retard"
                     else f"Proprietas — {copro.nom} : facture(s) à payer bientôt")
            _prevenir(db, copro, sujet, _corps(copro, sorted(lignes, key=lambda m: m.echeance), sorte == "retard"))
            for m in lignes:
                if sorte == "retard":
                    m.rappel_retard_le = maintenant
                    m.rappel_avant_le = m.rappel_avant_le or maintenant
                else:
                    m.rappel_avant_le = maintenant
            stats[sorte] += len(lignes)
    db.commit()
    return stats
