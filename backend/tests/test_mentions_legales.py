"""Mentions légales des documents produits (2e revue externe, octobre 2026).

1. Fonds de travaux : depuis le 1er janvier 2023, il est défini à l'article 14-2-1 de la loi
   du 10 juillet 1965 (l'article 14-2 traite désormais du plan pluriannuel de travaux).
   L'art. 19-2 vise « les cotisations au fonds de travaux mentionné à l'article 14-2-1 ».
2. Notifications : la voie électronique (lettre recommandée électronique) est la règle ;
   la lettre recommandée papier est réservée au copropriétaire qui a demandé la voie postale
   (loi de 1965, art. 42-1 ; décret n° 67-223, art. 64-1, rédaction du décret n° 2025-1292).
"""
from datetime import date

from app.models.ag import AG
from app.models.copropriete import Copropriete
from app.services.emailer import MENTION_CONVOCATION, pv_email_texte, situation_texte
from app.services.md_pdf import ART_19_2_TEXTE


def test_pdf_mise_en_demeure_cite_l_article_14_2_1():
    assert "article 14-2-1" in ART_19_2_TEXTE
    assert "article 14-2." not in ART_19_2_TEXTE


def test_email_fonds_de_travaux_cite_l_article_14_2_1():
    texte = situation_texte(Copropriete(nom="Les Tilleuls"), "Marie", "12", 0, 0, 0, 0, 0, "Le syndic")
    assert "art. 14-2-1" in texte
    assert "art. 14-2 " not in texte


def test_convocation_lrar_seulement_si_voie_postale_demandee():
    assert "par défaut" in MENTION_CONVOCATION
    assert "voie postale" in MENTION_CONVOCATION
    assert "42-1" in MENTION_CONVOCATION
    assert "art. 9 et 64" in MENTION_CONVOCATION          # mention existante conservée


def test_email_pv_lrar_seulement_si_voie_postale_demandee():
    ag = AG(date=date(2026, 11, 20), type_ag="annuelle")
    texte = pv_email_texte(Copropriete(nom="Les Tilleuls"), ag, "Le syndic")
    assert "voie postale" in texte
    assert "(électronique ou papier)" not in texte
