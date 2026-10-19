"""Vue consolidée multi-copropriétés : agrégation des comptes, impayés, AG et relances."""
from datetime import date

from fastapi import APIRouter, Depends
from app.core.money import D, arrondi, somme
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User, UserCopro
from app.models.copropriete import Copropriete
from app.models.exercice import Exercice
from app.models.mouvement import Mouvement
from app.models.lot import Lot
from app.models.ag import AG
from app.routes.relances import _etat_lots

router = APIRouter(prefix="/api", tags=["consolide"])
@router.get("/consolide")
def consolide(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Agrégation de toutes les copropriétés accessibles par le user."""
    liens = (db.query(UserCopro).filter(UserCopro.user_id == user.id)
             .order_by(UserCopro.principale.desc(), UserCopro.id).all())
    aujourdhui = date.today()
    immeubles = []
    tot_budget = tot_encaisse = tot_depense = tot_impayes = tot_ft_encours = D(0)
    tot_lots = 0

    for lien in liens:
        copro = db.query(Copropriete).filter(Copropriete.id == lien.copropriete_id).first()
        if not copro:
            continue
        ex = (db.query(Exercice).filter(Exercice.copropriete_id == copro.id)
              .order_by(Exercice.annee.desc()).first())
        lots = db.query(Lot).filter(Lot.copropriete_id == copro.id).all()
        mouvements = (db.query(Mouvement).filter(Mouvement.exercice_id == ex.id).all()) if ex else []
        encaisse = somme([m.montant for m in mouvements if m.type == "encaissement"])
        depense = somme([m.montant for m in mouvements if m.type == "depense"])
        budget = somme([b.montant for b in ex.budget_lines]) if ex else D(0)
        ft_encaisse = somme([m.montant for m in mouvements if m.type == "encaissement" and m.categorie == "fonds_travaux"])
        ft_depense = somme([m.montant for m in mouvements if m.type == "depense" and m.categorie == "fonds_travaux"])

        etats = _etat_lots(db, copro)
        impayes = [e for e in etats if (e.get("solde") or D(0)) > D("0.005")]
        total_impayes = somme([e["solde"] for e in impayes])

        prochaine_ag = (db.query(AG)
                        .filter(AG.copropriete_id == copro.id, AG.date >= aujourdhui)
                        .order_by(AG.date).first())

        tot_budget += budget
        tot_encaisse += encaisse
        tot_depense += depense
        tot_impayes += total_impayes
        tot_ft_encours += ft_encaisse - ft_depense
        tot_lots += len(lots)

        immeubles.append({
            "id": copro.id,
            "nom": copro.nom,
            "ville": copro.ville or "",
            "principale": bool(lien.principale),
            "lots": len(lots),
            "budget": arrondi(budget),
            "encaisse": arrondi(encaisse),
            "depense": arrondi(depense),
            "solde": arrondi(encaisse - depense),
            "impayes": arrondi(total_impayes),
            "nb_lots_retard": len(impayes),
            "ft_encours": arrondi(ft_encaisse - ft_depense),
            "relance_auto": bool(copro.relance_auto),
            "prochaine_ag": prochaine_ag.date.isoformat() if prochaine_ag else None,
            "prochaine_ag_heure": prochaine_ag.heure or "" if prochaine_ag else "",
        })

    # Prochaines AG sur toutes les copros (dans les 90 jours)
    copro_ids = [i["id"] for i in immeubles]
    ags_prochaines = []
    if copro_ids:
        ags = (db.query(AG).filter(AG.copropriete_id.in_(copro_ids), AG.date >= aujourdhui)
               .order_by(AG.date).limit(10).all())
        for ag in ags:
            copro = next((i for i in immeubles if i["id"] == ag.copropriete_id), None)
            if copro:
                ags_prochaines.append({
                    "ag_id": ag.id,
                    "copro_id": ag.copropriete_id,
                    "copro_nom": copro["nom"],
                    "date": ag.date.isoformat(),
                    "heure": ag.heure or "",
                    "type": ag.type_ag,
                    "statut": ag.statut,
                })

    return {
        "immeubles": immeubles,
        "totaux": {
            "immeubles": len(immeubles),
            "lots": tot_lots,
            "budget": arrondi(tot_budget),
            "encaisse": arrondi(tot_encaisse),
            "depense": arrondi(tot_depense),
            "solde": arrondi(tot_encaisse - tot_depense),
            "impayes": arrondi(tot_impayes),
            "ft_encours": arrondi(tot_ft_encours),
        },
        "ags_prochaines": ags_prochaines,
    }
