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



