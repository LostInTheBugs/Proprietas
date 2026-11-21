"""Tests de propriété sur l'argent et les majorités (avis de Perplexity relayé par Fred, 21/11/2026).

Au lieu de quelques exemples choisis, Hypothesis génère des centaines de copropriétés (nombre de lots,
tantièmes, montants, votes) et vérifie des règles qui doivent TOUJOURS tenir :
- une répartition tombe exactement au centime sur le montant, chaque part à moins d'un centime de sa part
  exacte, et le résultat ne dépend que des données (même entrée, même sortie) ;
- la répartition « par le budget, puis par la clé » (appel de provisions) retombe aussi sur le montant ;
- majorités : tout le monde pour → adoptée, tout le monde contre → rejetée ; passer un vote de « contre »
  à « pour » ne fait jamais rejeter une résolution adoptée ; la réduction de l'art. 22 ne laisse jamais un
  copropriétaire avec plus de la moitié des voix.
"""
from decimal import Decimal as D
from fractions import Fraction
from types import SimpleNamespace

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.money import arrondi
from app.services import cles
from app.services.country_rules import (_membres, _reduction_art22, calculer_statut_resolution,
                                        repartir_par_tantiemes, tantiemes_totaux)

REGLAGES = settings(max_examples=300, deadline=None)

# Montants au centime, positifs ou négatifs (remboursement, avoir), jusqu'à 10 millions d'euros.
montants = st.integers(min_value=-1_000_000_000, max_value=1_000_000_000).map(lambda c: D(c) / D(100))
tantiemes = st.lists(st.integers(min_value=0, max_value=10_000), min_size=1, max_size=60).filter(lambda t: sum(t) > 0)


def _lots(liste, proprietaires=None):
    return [SimpleNamespace(id=i + 1, tantiemes=t, numero=str(i + 1),
                            proprietaire_id=(proprietaires[i] if proprietaires else i + 1))
            for i, t in enumerate(liste)]


@REGLAGES
@given(montant=montants, tants=tantiemes, taux=st.sampled_from([D(0), D(5), D("7.5"), D(10)]))
def test_repartition_tombe_au_centime(montant, tants, taux):
    lots = _lots(tants)
    parts = repartir_par_tantiemes(montant, lots, taux)
    total = sum(tants)
    assert sum(p["montant_charges"] for p in parts) == montant
    for p, t in zip(parts, tants):
        exacte = montant * D(t) / D(total)
        assert abs(p["montant_charges"] - exacte) < D("0.01")
        assert p["montant_charges"] == arrondi(p["montant_charges"])           # jamais plus de deux décimales
        if t == 0:
            assert p["montant_charges"] == 0
    if taux:
        fonds = arrondi(montant * taux / D(100))
        assert sum(p["montant_fonds_travaux"] for p in parts) == fonds
    again = repartir_par_tantiemes(montant, _lots(tants), taux)                     # même entrée, même sortie
    assert [p["montant_charges"] for p in again] == [p["montant_charges"] for p in parts]


@REGLAGES
@given(montant=montants.filter(lambda m: m != 0),
       budget=st.dictionaries(st.sampled_from([None, 1, 2, 3]), st.integers(min_value=1, max_value=10_000_000),
                              min_size=1),
       tants=st.lists(st.integers(min_value=1, max_value=1000), min_size=2, max_size=20))
def test_appel_reparti_selon_le_budget_puis_par_cle(montant, budget, tants):
    """Appel de provisions : partagé entre les clés comme le budget, puis chaque part par sa clé ;
    le total des lots retombe exactement sur le montant appelé."""
    lots = _lots(tants)
    par_cle = {None: lots, 1: lots[::2], 2: lots[1::2], 3: lots[:1]}
    budget_euros = {k: D(v) / D(100) for k, v in budget.items()}
    anciens = cles.lots_de, cles.budget_par_cle
    cles.lots_de = lambda db, copro_id, cle_id: par_cle[cle_id]
    cles.budget_par_cle = lambda db, exercice_id: budget_euros
    try:
        parts = cles.repartir_selon_budget(None, 1, 1, montant)
    finally:
        cles.lots_de, cles.budget_par_cle = anciens
    assert sum(parts.values()) == montant
    assert all(v == arrondi(v) for v in parts.values())


# ---------------------------------------------------------------- majorités
proprietes = st.lists(st.tuples(st.integers(min_value=1, max_value=2000), st.integers(min_value=1, max_value=8)),
                      min_size=1, max_size=25)   # (tantièmes, propriétaire)


def _votes(lots, voix):
    return [SimpleNamespace(lot_id=l.id, voix=v) for l, v in zip(lots, voix)]


@REGLAGES
@given(donnees=proprietes, majorite=st.sampled_from(["art24", "art25", "art26", "unanimite"]))
def test_tous_pour_adoptee_tous_contre_rejetee(donnees, majorite):
    lots = _lots([t for t, _ in donnees], [p for _, p in donnees])
    r = SimpleNamespace(majorite=majorite)
    assert calculer_statut_resolution(r, lots, _votes(lots, ["pour"] * len(lots)))["statut"] == "adoptee"
    assert calculer_statut_resolution(r, lots, _votes(lots, ["contre"] * len(lots)))["statut"] == "rejetee"


@REGLAGES
@given(donnees=proprietes, majorite=st.sampled_from(["art24", "art25", "art26", "unanimite"]),
       voix=st.lists(st.sampled_from(["pour", "contre", "abstention", "null"]), min_size=25, max_size=25),
       index=st.integers(min_value=0, max_value=24))
def test_un_contre_qui_passe_pour_ne_fait_jamais_rejeter(donnees, majorite, voix, index):
    lots = _lots([t for t, _ in donnees], [p for _, p in donnees])
    voix = voix[:len(lots)]
    i = index % len(lots)
    voix[i] = "contre"
    r = SimpleNamespace(majorite=majorite)
    avant = calculer_statut_resolution(r, lots, _votes(lots, voix))["statut"]
    voix[i] = "pour"
    apres = calculer_statut_resolution(r, lots, _votes(lots, voix))["statut"]
    assert not (avant == "adoptee" and apres == "rejetee")


@REGLAGES
@given(donnees=proprietes)
def test_reduction_art22_jamais_plus_de_la_moitie(donnees):
    lots = _lots([t for t, _ in donnees], [p for _, p in donnees])
    membres = _membres(lots)
    poids, total_ref, reduit = _reduction_art22(lots, membres, tantiemes_totaux(lots))
    assert sum(poids.values()) == total_ref
    if len(membres) > 2:
        for info in membres.values():
            assert sum(poids[l.id] for l in info["lots"]) * 2 <= total_ref
    if reduit is None:
        assert total_ref == tantiemes_totaux(lots)
    else:
        assert all(isinstance(p, (int, Fraction)) for p in poids.values())
