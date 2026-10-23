"""Socle commun PDF : polices DejaVu embarquées + styles reportlab."""
import os
from copy import copy
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import TableStyle

_FONTS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")

_fonts_registered = False
_STYLES = {}


def register_fonts():
    global _fonts_registered
    if _fonts_registered:
        return
    pdfmetrics.registerFont(TTFont("DejaVu", os.path.join(_FONTS_DIR, "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", os.path.join(_FONTS_DIR, "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Oblique", os.path.join(_FONTS_DIR, "DejaVuSans-Oblique.ttf")))
    _fonts_registered = True


def style(name: str, **kw) -> ParagraphStyle:
    """Style partagé, cloné à chaque appel pour éviter les fuites entre documents."""
    if name not in _STYLES:
        base = {
            "titre": dict(fontName="DejaVu-Bold", fontSize=15, leading=20, alignment=TA_CENTER, spaceAfter=4),
            "sous_titre": dict(fontName="DejaVu", fontSize=11, leading=16, alignment=TA_CENTER, textColor=colors.HexColor("#444444"), spaceAfter=10),
            "section": dict(fontName="DejaVu-Bold", fontSize=11, leading=15, spaceBefore=8, spaceAfter=5),
            "normal": dict(fontName="DejaVu", fontSize=9.5, leading=13),
            "normal_bold": dict(fontName="DejaVu-Bold", fontSize=9.5, leading=13),
            "small": dict(fontName="DejaVu", fontSize=8.5, leading=12),
            "legal": dict(fontName="DejaVu", fontSize=7.8, leading=10, textColor=colors.HexColor("#666666"), alignment=TA_JUSTIFY),
            "cell": dict(fontName="DejaVu", fontSize=9, leading=12),
            "th": dict(fontName="DejaVu-Bold", fontSize=9, leading=12),
        }[name]
        _STYLES[name] = ParagraphStyle(name, **base)
    s = copy(_STYLES[name])
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def table_style(header_bg: str = "#e2e8f0") -> TableStyle:
    return TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ])


def page_margins():
    return dict(
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
    )


def fmt_eur(v: float | Decimal | int | None) -> str:
    """Format monétaire français : 1 234,56 €"""
    from app.core.money import to_money
    return f"{to_money(v):,.2f} €".replace(",", " ").replace(".", ",")
