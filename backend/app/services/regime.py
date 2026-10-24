"""Régime de la copropriété calculé depuis la base (lots et budgets prévisionnels).

Les règles elles-mêmes sont dans country_rules (art. 41-8) ; ce module ne fait que lire les
données, pour que /recap et les assemblées utilisent exactement le même calcul.
"""
from sqlalchemy.orm import Session

from app.core.money import somme
from app.models.exercice import Exercice
from app.models.lot import Lot
from app.services.country_rules import regime_petite_copro


def regime_copro(db: Session, copro_id: int) -> dict:
    """{"petite": bool, "nb_lots_principaux": int, "budget_moyen": Decimal | None}."""
    lots = db.query(Lot).filter(Lot.copropriete_id == copro_id).all()
    budgets = {e.annee: somme(b.montant for b in e.budget_lines)
               for e in db.query(Exercice).filter(Exercice.copropriete_id == copro_id).all()}
    return regime_petite_copro(lots, budgets)
