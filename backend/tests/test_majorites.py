"""Moteur de majorités (module France) — art. 24, 25, 26, unanimité,
régime des 2 copropriétaires (art. 41-16), passerelle art. 25-1.

Un cas nominal et un cas limite par majorité.
"""
from app.models.ag import Resolution, Vote
from app.models.lot import Lot
from app.services.country_rules import calculer_statut_resolution


def _lot(id_, tantiemes, prop=None):
    return Lot(id=id_, numero=str(id_), tantiemes=tantiemes, proprietaire_id=prop)


def _vote(lot_id, voix):
    return Vote(lot_id=lot_id, voix=voix)


def _res(majorite, **kw):
    return Resolution(id=1, ag_id=1, numero=1, libelle="Résolution", majorite=majorite, **kw)


def _quatre_lots():
    """4 lots, 1000 millièmes, 3 copropriétaires distincts."""
    return [_lot(1, 280, 101), _lot(2, 260, 102), _lot(3, 240, 102), _lot(4, 220, 103)]


def _quatre_lots_egaux():
    """4 lots égaux de 250 millièmes (cas limites 500/500)."""
    return [_lot(1, 250, 101), _lot(2, 250, 102), _lot(3, 250, 103), _lot(4, 250, 104)]


# ---------- Art. 24 : majorité des voix exprimées ----------
def test_art24_nominal_adoptee():
    # 700 pour / 300 contre (exprimés = 1000) → pour > 50 % des exprimés
    r = _res("art24")
    votes = [_vote(1, "pour"), _vote(2, "pour"), _vote(3, "pour"), _vote(4, "contre")]
    res = calculer_statut_resolution(r, _quatre_lots(), votes)
    assert res["statut"] == "adoptee"
    assert res["pour"] == 780 and res["contre"] == 220


def test_art24_cas_limite_egalite_rejetee():
    # 500 pour / 500 contre → 50 % exactement, pas > 50 % → rejetée
    r = _res("art24")
    votes = [_vote(1, "pour"), _vote(2, "pour"), _vote(3, "contre"), _vote(4, "contre")]
    res = calculer_statut_resolution(r, _quatre_lots_egaux(), votes)
    assert res["statut"] == "rejetee"
    assert res["pour"] == 500 and res["contre"] == 500


def test_art24_abstentions_exclues():
    # Abstentions (240) ne comptent pas : 280 pour / 220 contre → pour > 50 % des exprimés
    r = _res("art24")
    votes = [_vote(1, "pour"), _vote(2, "abstention"), _vote(3, "abstention"), _vote(4, "contre")]
    res = calculer_statut_resolution(r, _quatre_lots(), votes)
    assert res["statut"] == "adoptee"
    assert res["abstention"] == 500


def test_art24_aucun_exprime_rejetee():
    r = _res("art24")
    res = calculer_statut_resolution(r, _quatre_lots(), [_vote(1, "abstention")])
    assert res["statut"] == "rejetee"


# ---------- Art. 25 : majorité de tous les copropriétaires ----------
def test_art25_nominal_adoptee():
    # 780 > 500 → adoptée
    r = _res("art25")
    votes = [_vote(1, "pour"), _vote(2, "pour"), _vote(3, "pour"), _vote(4, "contre")]
    res = calculer_statut_resolution(r, _quatre_lots(), votes)
    assert res["statut"] == "adoptee"


def test_art25_cas_limite_500_500_rejetee():
    # 500 pour exactement → pas > 50 % → rejetée
    r = _res("art25")
    votes = [_vote(1, "pour"), _vote(2, "pour"), _vote(3, "contre"), _vote(4, "contre")]
    res = calculer_statut_resolution(r, _quatre_lots_egaux(), votes)
    assert res["statut"] == "rejetee"


# ---------- Art. 26 : 2/3 des voix de tous ----------
def test_art26_nominal_adoptee():
    # 780 >= 666,67 → adoptée
    r = _res("art26")
    votes = [_vote(1, "pour"), _vote(2, "pour"), _vote(3, "pour"), _vote(4, "contre")]
    res = calculer_statut_resolution(r, _quatre_lots(), votes)
    assert res["statut"] == "adoptee"


def test_art26_cas_limite_660_rejetee():
    # 660 < 666,67 (2/3 de 1000) → rejetée
    lots = [_lot(1, 220, 101), _lot(2, 220, 102), _lot(3, 220, 103), _lot(4, 340, 104)]
    r = _res("art26")
    votes = [_vote(1, "pour"), _vote(2, "pour"), _vote(3, "pour")]
    res = calculer_statut_resolution(r, lots, votes)
    assert res["statut"] == "rejetee"
    assert res["pour"] == 660


# ---------- Unanimité ----------
def test_unanimite_nominal_adoptee():
    r = _res("unanimite")
    votes = [_vote(1, "pour"), _vote(2, "pour"), _vote(3, "pour"), _vote(4, "pour")]
    res = calculer_statut_resolution(r, _quatre_lots(), votes)
    assert res["statut"] == "adoptee"


def test_unanimite_cas_limite_une_abstention_rejetee():
    # Une abstention = pas 100 % de « pour » → rejetée
    r = _res("unanimite")
    votes = [_vote(1, "pour"), _vote(2, "pour"), _vote(3, "pour"), _vote(4, "abstention")]
    res = calculer_statut_resolution(r, _quatre_lots(), votes)
    assert res["statut"] == "rejetee"


# ---------- Régime des 2 copropriétaires (art. 41-16) ----------
def test_regime_deux_art24_moitie_plus():
    # 2 copropriétaires distincts ; 780 (> 50 %) décide seul en art. 24
    lots = [_lot(1, 600, 101), _lot(2, 400, 102)]
    r = _res("art24")
    votes = [_vote(1, "pour"), _vote(2, "contre")]
    res = calculer_statut_resolution(r, lots, votes)
    assert res["statut"] == "adoptee"
    assert res["regime_deux"] is True


def test_regime_deux_art24_egale_moitie_rejetee():
    # 500 = 50 % exactement (pas > 50 %) → rejetée
    lots = [_lot(1, 500, 101), _lot(2, 500, 102)]
    r = _res("art24")
    votes = [_vote(1, "pour"), _vote(2, "contre")]
    res = calculer_statut_resolution(r, lots, votes)
    assert res["statut"] == "rejetee"


def test_regime_deux_art25_deux_tiers():
    # art. 41-16 : art. 25 exige 2/3 en régime 2 copropriétaires → 600 < 666,67 → rejetée
    lots = [_lot(1, 600, 101), _lot(2, 400, 102)]
    r = _res("art25")
    votes = [_vote(1, "pour"), _vote(2, "contre")]
    res = calculer_statut_resolution(r, lots, votes)
    assert res["statut"] == "rejetee"


def test_regime_deux_art25_deux_tiers_atteint():
    lots = [_lot(1, 700, 101), _lot(2, 300, 102)]
    r = _res("art25")
    votes = [_vote(1, "pour"), _vote(2, "contre")]
    res = calculer_statut_resolution(r, lots, votes)
    assert res["statut"] == "adoptee"


# ---------- Passerelle art. 25-1 (repli art. 25 → art. 24) ----------
def test_passerelle_25_1_rejet_art25_puis_adoption_art24():
    """Une résolution rejetée en art. 25 peut être adoptée en art. 24 sur les
    mêmes voix (mécanisme de la passerelle légale)."""
    lots = _quatre_lots_egaux()
    votes = [_vote(1, "pour"), _vote(2, "pour"), _vote(3, "contre"), _vote(4, "abstention")]  # 500 pour / 250 contre / 250 abst.
    r25 = _res("art25")
    res25 = calculer_statut_resolution(r25, lots, votes)
    assert res25["statut"] == "rejetee"  # 500 pas > 500
    # Mêmes voix sous le régime art. 24 : 500 pour > 50 % des exprimés (750) → adoptée
    r24 = _res("art24")
    res24 = calculer_statut_resolution(r24, lots, votes)
    assert res24["statut"] == "adoptee"


# ---------- Art. 22 al. 2 : réduction des voix du copropriétaire majoritaire ----------
def _lots_majoritaire():
    """A = 600/1000 (> moitié) ; B et C = 200 chacun. 3 copropriétaires distincts."""
    return [_lot(1, 600, 101), _lot(2, 200, 102), _lot(3, 200, 103)]


def test_art22_reduction_art25_majoritaire_seul_rejete():
    # A réduit à 400 (= 200 + 200), total de référence 800 : 400 n'est pas > 400.
    r = _res("art25")
    res = calculer_statut_resolution(r, _lots_majoritaire(), [_vote(1, "pour"), _vote(2, "contre"), _vote(3, "contre")])
    assert res["statut"] == "rejetee"
    assert res["pour"] == 400 and res["total"] == 800
    assert res["reduction_art22"] == 101


def test_art22_reduction_art24_majoritaire_seul_rejete():
    # Exprimés : 400 pour / 400 contre → égalité → rejetée.
    r = _res("art24")
    res = calculer_statut_resolution(r, _lots_majoritaire(), [_vote(1, "pour"), _vote(2, "contre"), _vote(3, "contre")])
    assert res["statut"] == "rejetee"


def test_art22_reduction_art25_majoritaire_plus_un_adopte():
    # 400 + 200 = 600 > 400 → adoptée.
    r = _res("art25")
    res = calculer_statut_resolution(r, _lots_majoritaire(), [_vote(1, "pour"), _vote(2, "pour"), _vote(3, "contre")])
    assert res["statut"] == "adoptee"
    assert res["pour"] == 600


def test_art22_pas_de_reduction_sans_majoritaire():
    res = calculer_statut_resolution(_res("art25"), _quatre_lots(), [_vote(1, "pour")])
    assert res["reduction_art22"] is None
    assert res["total"] == 1000


# ---------- Art. 26 : double majorité (membres + 2/3 des voix) ----------
def _cinq_coproprietaires():
    return [_lot(1, 340, 101), _lot(2, 340, 102), _lot(3, 110, 103), _lot(4, 105, 104), _lot(5, 105, 105)]


def test_art26_deux_tiers_des_voix_mais_minorite_des_membres_rejete():
    # 680/1000 ≥ 2/3 des voix, mais 2 membres « pour » sur 5 : pas la majorité des membres.
    votes = [_vote(1, "pour"), _vote(2, "pour"), _vote(3, "contre"), _vote(4, "contre"), _vote(5, "contre")]
    res = calculer_statut_resolution(_res("art26"), _cinq_coproprietaires(), votes)
    assert res["statut"] == "rejetee"
    assert res["membres_pour"] == 2 and res["nb_membres"] == 5


def test_art26_double_majorite_atteinte_adopte():
    # 790/1000 et 3 membres sur 5.
    votes = [_vote(1, "pour"), _vote(2, "pour"), _vote(3, "pour"), _vote(4, "contre"), _vote(5, "contre")]
    res = calculer_statut_resolution(_res("art26"), _cinq_coproprietaires(), votes)
    assert res["statut"] == "adoptee"


def test_art26_membre_a_plusieurs_lots_compte_une_fois():
    # _quatre_lots : le propriétaire 102 a 2 lots. 3 membres au total.
    # Lots 2 et 3 pour (500) + lot 1 pour (280) = 780 ≥ 667, et 2 membres sur 3 → adoptée.
    votes = [_vote(1, "pour"), _vote(2, "pour"), _vote(3, "pour"), _vote(4, "contre")]
    res = calculer_statut_resolution(_res("art26"), _quatre_lots(), votes)
    assert res["nb_membres"] == 3 and res["membres_pour"] == 2
    assert res["statut"] == "adoptee"
