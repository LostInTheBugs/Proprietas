"""Tests for money helpers and tantième apportionment."""

from decimal import Decimal
from app.core.money import to_money


class TestToMoney:
    """to_money : float/int → Decimal avec arrondi ROUND_HALF_UP à 2 décimales."""

    def test_from_float(self):
        assert to_money(19.99) == Decimal("19.99")

    def test_from_int(self):
        assert to_money(100) == Decimal("100.00")

    def test_from_decimal(self):
        assert to_money(Decimal("42.50")) == Decimal("42.50")

    def test_from_string(self):
        assert to_money("33.33") == Decimal("33.33")

    def test_rounding(self):
        # 19.995 → 20.00 (ROUND_HALF_UP)
        assert to_money(19.995) == Decimal("20.00")

    def test_negative(self):
        assert to_money(-5.01) == Decimal("-5.01")

    def test_none(self):
        assert to_money(None) == Decimal("0.00")

    def test_too_many_decimals(self):
        assert to_money(1.005) == Decimal("1.01")
"""Tests for money helpers and tantième apportionment."""

from decimal import Decimal
from app.core.money import to_money, D, somme
from app.services.country_rules import repartir_par_tantiemes


class _Lot:
    """Lot factice pour les tests."""
    def __init__(self, numero, tantiemes):
        self.numero = numero
        self.tantiemes = tantiemes


def test_fonds_travaux_reparti_depuis_le_total():
    lots = [_Lot(1, 333), _Lot(2, 333), _Lot(3, 334)]
    parts = repartir_par_tantiemes(D("12345.67"), lots, D("5"))
    assert somme(p["montant_charges"] for p in parts) == D("12345.67")
    assert somme(p["montant_fonds_travaux"] for p in parts) == D("617.28")  # arrondi(12345.67 × 5 %)
    assert [p["montant_fonds_travaux"] for p in parts] == [D("205.56"), D("205.55"), D("206.17")]
    assert all(isinstance(p["montant_charges"], Decimal) for p in parts)
