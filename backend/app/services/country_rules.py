"""Moteur de règles par pays — module France (V1).

Références :
- Loi n° 65-557 du 10 juillet 1965 (statut de la copropriété)
- Ordonnance n° 2019-1101 (régime des petites copropriétés, art. 41-8 et suiv.)
- Loi ALUR / ELAN : fonds de travaux obligatoire (plus d'exemption < 10 lots),
  taux minimum 5 % du budget prévisionnel (ou 2,5 % du PPT + 5 % budget avec PPT).

Majorités (art. 24, 25, 26) :
- art24 : majorité des voix exprimées des copropriétaires présents, représentés
  ou ayant voté par correspondance (les abstentions ne comptent pas).
- art25 : majorité des voix de tous les copropriétaires (> 50 % des millièmes).
- art26 : majorité des 2/3 des voix de tous les copropriétaires.
- unanimite : 100 % des voix de tous les copropriétaires.
- Régime « 2 copropriétaires » (art. 41-16) : si le nombre de copropriétaires
  distincts est <= 2, le copropriétaire détenant plus de la moitié des voix peut
  prendre seul les décisions de l'art. 24, et celui détenant au moins 2/3 des
  voix celles de l'art. 25 (budget et approbation des comptes exclus).
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from app.core.money import D, arrondi, to_money, somme

MAJORITES = {
    "art24": {
        "label": "Majorité simple (art. 24)",
        "description": "Majorité des voix exprimées des présents, représentés ou ayant voté par correspondance (abstentions exclues).",
    },
    "art25": {
        "label": "Majorité absolue (art. 25)",
        "description": "Majorité des voix de tous les copropriétaires (> 50 % des millièmes).",
    },
    "art26": {
        "label": "Majorité des 2/3 (art. 26)",
        "description": "Majorité des 2/3 des voix de tous les copropriétaires.",
    },
    "unanimite": {
        "label": "Unanimité",
        "description": "Tous les copropriétaires doivent voter pour.",
    },
}


def tantiemes_totaux(lots) -> int:
    return sum(l.tantiemes for l in lots) or 1000


def nb_coproprietaires(lots) -> int:
    """Nombre de copropriétaires distincts (par lot avec propriétaire)."""
    owners = {l.proprietaire_id for l in lots if l.proprietaire_id}
    return len(owners)


def calculer_statut_resolution(resolution, lots, votes) -> dict:
    """Calcule le statut d'une résolution selon les règles françaises.

    Retourne un dict : {statut, pour_t, contre_t, abst_t, total_t, quorum_t, detail}
    """
    total = tantiemes_totaux(lots)
    # Les votes sont rattachés à des lots ; chaque lot porte ses millièmes.
    poids = {l.id: l.tantiemes for l in lots}
    pour = sum(poids.get(v.lot_id, 0) for v in votes if v.voix == "pour")
    contre = sum(poids.get(v.lot_id, 0) for v in votes if v.voix == "contre")
    abst = sum(poids.get(v.lot_id, 0) for v in votes if v.voix == "abstention")

    nb_owners = nb_coproprietaires(lots)
    regime_deux = nb_owners <= 2

    if resolution.majorite == "art24":
        exprimes = pour + contre
        quorum = exprimes
        if regime_deux:
            # art. 41-16 : le copropriétaire avec > 50 % des voix décide seul
            adoptee = pour > total / 2
            detail = "Régime 2 copropriétaires (art. 41-16) : décision prise par le copropriétaire détenant plus de la moitié des voix."
        else:
            adoptee = exprimes > 0 and pour > exprimes / 2
            detail = "Majorité des voix exprimées (art. 24) : pour / (pour + contre) > 50 %."
    elif resolution.majorite == "art25":
        quorum = total
        if regime_deux:
            adoptee = pour >= 2 * total / 3
            detail = "Régime 2 copropriétaires (art. 41-16) : décision prise par le copropriétaire détenant au moins 2/3 des voix."
        else:
            adoptee = pour > total / 2
            detail = "Majorité des voix de tous les copropriétaires (art. 25) : pour > 50 % des millièmes."
    elif resolution.majorite == "art26":
        quorum = total
        adoptee = pour >= 2 * total / 3
        detail = "Majorité des 2/3 des voix de tous les copropriétaires (art. 26)."
    else:  # unanimite
        quorum = total
        adoptee = pour == total and contre == 0
        detail = "Unanimité requise : tous les copropriétaires doivent voter pour."

    statut = "adoptee" if adoptee else "rejetee"
    return {
        "statut": statut,
        "pour": pour,
        "contre": contre,
        "abstention": abst,
        "total": total,
        "quorum": quorum,
        "regime_deux": regime_deux,
        "detail": detail,
    }


def regles_fonds_travaux(copro) -> dict:
    """Recommandation légale sur le fonds de travaux (France)."""
    taux_min = 5.0
    return {
        "obligatoire": True,
        "taux_minimum_pct": taux_min,
        "texte": (
            "Fonds de travaux obligatoire (loi ALUR, modifiée) dès 10 ans après "
            "réception des travaux, quel que soit le nombre de lots. "
            "Cotisation annuelle minimale : 5 % du budget prévisionnel "
            "(ou 2,5 % du plan pluriannuel de travaux + 5 % du budget si PPT voté). "
            "Versement sur compte bancaire séparé, montant voté chaque année en AG "
            "(art. 25, repli art. 24 si 1/3 des voix au premier vote)."
        ),
    }


def _plus_fort_reste(montant: Decimal, lots) -> list[int]:
    """Répartir *montant* (en centimes) entre lots au prorata.

    Retourne une liste d'entiers (centimes) dont la somme est exactement
    montant, avec la méthode du plus fort reste.
    """
    total = tantiemes_totaux(lots)
    if total <= 0 or not lots:
        return []
    parts: list[int] = []
    fractions: list[Decimal] = []
    for lot in lots:
        brut = D(montant) * D(lot.tantiemes) / D(total)
        entier = int(brut.to_integral_value(rounding=ROUND_FLOOR))
        parts.append(entier)
        fractions.append(brut - D(entier))
    n_restes = int(montant) - sum(parts)
    indices_tries = sorted(range(len(fractions)), key=lambda i: fractions[i], reverse=True)
    for idx in indices_tries[:n_restes]:
        parts[idx] += 1
    return parts


def repartir_par_tantiemes(montant, lots, fonds_travaux_taux: Decimal = D(0)) -> list:
    """Répartit un montant entre les lots au prorata des millièmes.

    Retourne une liste de dicts {lot, montant_charges, montant_fonds_travaux?}.
    Méthode du plus fort reste — tout reste en Decimal.
    Le fonds de travaux est arrondi une seule fois, puis réparti.
    """
    montant = to_money(montant)
    charges = _plus_fort_reste(montant * D(100), lots)
    parts: list[dict] = []
    for i, lot in enumerate(lots):
        euros = D(charges[i]) / D(100)
        parts.append({"lot": lot, "montant_charges": euros})
    if fonds_travaux_taux > D(0):
        fonds_total = _plus_fort_reste(arrondi(montant * fonds_travaux_taux / D(100)) * D(100), lots)
        for i, p in enumerate(parts):
            p["montant_fonds_travaux"] = D(fonds_total[i]) / D(100)
    return parts
