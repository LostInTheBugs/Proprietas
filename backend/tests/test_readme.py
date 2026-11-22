"""Le README dit ce que fait l'application (avis de Grok relayé par Fred, 22/11/2026).

Grok a lu dans la feuille de route que le vote des charges spéciales en AG manquait encore : il est fait depuis
la tâche 94. Ces tests gardent la liste des fonctionnalités et la feuille de route à jour sur ces points.
"""
from pathlib import Path

README = (Path(__file__).resolve().parents[2] / "README.md").read_text(encoding="utf-8")


def _section(titre: str) -> str:
    """Texte de la section `## titre`, jusqu'à la section suivante de même niveau."""
    debut = README.index(f"\n## {titre}\n")
    fin = README.find("\n## ", debut + 1)
    return README[debut:fin if fin != -1 else None]


def test_fonctionnalites_recentes_listees():
    f = _section("Fonctionnalités")
    for mot in ("**Mandats**", "**Réunion en visioconférence**", "**Vote en direct**", "**Supervision du serveur**"):
        assert mot in f, mot


def test_feuille_de_route_sans_fonction_deja_faite():
    r = _section("Feuille de route")
    assert "Charges spéciales en AG" not in r          # fait : « Vote sur une clé de répartition »
    assert "OneDrive" in r and "recommandées" in r     # vrais manques, gardés


def test_avances_sans_contradiction():
    assert "aucune fonction d'avance" not in README    # les avances existent (tâche 81)
