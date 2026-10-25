"""Fin des délais : report au premier jour ouvrable (code de procédure civile, art. 642).

« Le délai qui expirerait normalement un samedi, un dimanche ou un jour férié ou chômé est
prorogé jusqu'au premier jour ouvrable suivant. »

Jours fériés légaux : code du travail, art. L3133-1. En Alsace-Moselle (départements 57, 67
et 68), s'y ajoutent le Vendredi saint et le 26 décembre (art. L3134-13). La copropriété est
rattachée à l'Alsace-Moselle par son code postal.
"""
from datetime import date, timedelta
from functools import lru_cache

DEPARTEMENTS_ALSACE_MOSELLE = ("57", "67", "68")


def paques(annee: int) -> date:
    """Dimanche de Pâques (calendrier grégorien, algorithme de Meeus/Jones/Butcher)."""
    a, b, c = annee % 19, annee // 100, annee % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mois = (h + l - 7 * m + 114) // 31
    jour = (h + l - 7 * m + 114) % 31 + 1
    return date(annee, mois, jour)


@lru_cache(maxsize=64)
def jours_feries(annee: int, alsace_moselle: bool = False) -> frozenset:
    p = paques(annee)
    feries = {
        date(annee, 1, 1), p + timedelta(days=1), date(annee, 5, 1), date(annee, 5, 8),
        p + timedelta(days=39), p + timedelta(days=50), date(annee, 7, 14), date(annee, 8, 15),
        date(annee, 11, 1), date(annee, 11, 11), date(annee, 12, 25),
    }
    if alsace_moselle:
        feries |= {p - timedelta(days=2), date(annee, 12, 26)}
    return frozenset(feries)


def est_alsace_moselle(code_postal) -> bool:
    cp = (code_postal or "").strip()
    return len(cp) == 5 and cp[:2] in DEPARTEMENTS_ALSACE_MOSELLE


def est_ouvrable(d: date, alsace_moselle: bool = False) -> bool:
    return d.weekday() < 5 and d not in jours_feries(d.year, alsace_moselle)


def reporter(echeance: date, alsace_moselle: bool = False) -> date:
    """Échéance reportée au premier jour ouvrable si elle tombe un samedi, un dimanche ou un
    jour férié (art. 642 CPC)."""
    d = echeance
    while not est_ouvrable(d, alsace_moselle):
        d += timedelta(days=1)
    return d
