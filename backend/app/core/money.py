"""Helper monétaire : Decimal avec arrondi ROUND_HALF_UP (base 10).

Usage :
    - D("12.50")      → Decimal("12.50")
    - to_money(12.5)  → Decimal("12.50")
    - arrondi(d)      → d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
"""
from collections.abc import Iterable
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation


def D(v: str | int | float | Decimal) -> Decimal:
    """Convertir en Decimal sans perte de précision.

    Accepte str, int, float ou Decimal.
    Pour les float, la conversion passe par str() pour éviter
    l'imprécision binaire (ex: D(0.1) == Decimal("0.1"), pas 0.10000000000000001).
    """
    if isinstance(v, Decimal):
        return v
    if isinstance(v, str):
        try:
            return Decimal(v)
        except InvalidOperation:
            return Decimal(str(v))
    # int ou float
    return Decimal(str(v))


def to_money(v: str | int | float | Decimal | None) -> Decimal:
    """Convertir un montant en Decimal arrondi à 2 décimales (ROUND_HALF_UP).

    `v` peut être None (retourne "0.00").
    """
    if v is None:
        return Decimal("0.00")
    return arrondi(D(v))


def arrondi(v: Decimal) -> Decimal:
    """Arrondir un Decimal à 2 décimales avec ROUND_HALF_UP (arrondi comptable)."""
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def somme(valeurs: Iterable[Decimal]) -> Decimal:
    """Somme exacte de Decimal.

    Utilise sum(..., Decimal("0")) pour éviter que sum() sur iterable vide retourne 0 (int).
    """
    return sum(valeurs, D(0))





# ---------------------------------------------------------------- saisies (schémas d'entrée)
LIMITE_MONTANT = Decimal("10000000000")   # Numeric(12,2) : au plus 9 999 999 999,99
LIMITE_TAUX = Decimal("1000")             # Numeric(7,4)  : au plus 999,9999


def decimal_saisi(v, quantum: Decimal, limite: Decimal) -> Decimal | None:
    """Valide et arrondit une valeur SAISIE (corps de requête), avant toute écriture en base.

    - accepte int, float, str ou Decimal ; None reste None (champ optionnel) ;
    - refuse les booléens, le texte non numérique, NaN / ±Infinity et les valeurs hors
      limites de la colonne (ValueError → 422 côté API, au lieu d'un 500 plus loin) ;
    - arrondit au `quantum` (0.01 ou 0.0001) en ROUND_HALF_UP.
    Sans cela, SQLite stocke la valeur brute (10.005) alors que PostgreSQL l'arrondit.
    """
    if v is None:
        return None
    if isinstance(v, bool):
        raise ValueError("Montant invalide")
    try:
        d = D(v)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Montant invalide") from None
    if not d.is_finite():
        raise ValueError("Montant invalide (valeur non finie)")
    if abs(d) >= limite:                  # avant quantize : 1e30 dépasserait la précision Decimal
        raise ValueError("Montant hors limites")
    d = d.quantize(quantum, rounding=ROUND_HALF_UP)
    if abs(d) >= limite:                  # 9999999999.995 s'arrondit à la limite
        raise ValueError("Montant hors limites")
    return d
