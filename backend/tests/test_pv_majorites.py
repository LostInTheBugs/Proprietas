"""Procès-verbal : il doit rendre compte de la réduction art. 22, du décompte des
membres (art. 26) et du second vote immédiat (art. 25-1 / 26-1), dans l'ordre de l'AG."""
from datetime import date
from io import BytesIO

from pypdf import PdfReader

from app.models.ag import AG, Resolution, Vote
from app.models.lot import Lot
from app.services.pv_pdf import generer_pv_pdf


def _texte(buf: BytesIO) -> str:
    reader = PdfReader(BytesIO(buf.getvalue()))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _pv(db, copro):
    # 3 lots sans propriétaire saisi = 3 membres ; le lot 1 (600/1000) est majoritaire.
    lots = [Lot(copropriete_id=copro.id, numero=str(i), tantiemes=t)
            for i, t in ((1, 600), (2, 200), (3, 200))]
    db.add_all(lots)
    ag = AG(copropriete_id=copro.id, date=date(2026, 11, 20))
    db.add(ag)
    db.flush()
    r1 = Resolution(ag_id=ag.id, numero=1, libelle="Ravalement", majorite="art25")
    r2 = Resolution(ag_id=ag.id, numero=2, libelle="Modification du règlement", majorite="art26")
    db.add_all([r1, r2])
    db.flush()
    # Second vote de la résolution 1 (passerelle 25-1), créé APRÈS la résolution 2
    sv = Resolution(ag_id=ag.id, numero=1, libelle="Ravalement — second vote (art. 25-1)",
                    majorite="art24", second_vote_de_id=r1.id)
    db.add(sv)
    db.flush()
    for res, voix in ((r1, ("pour", "contre", "contre")),
                      (r2, ("pour", "pour", "contre")),
                      (sv, ("pour", "pour", "contre"))):
        for lot, v in zip(lots, voix):
            db.add(Vote(resolution_id=res.id, lot_id=lot.id, voix=v))
    db.commit()
    db.refresh(ag)
    return _texte(generer_pv_pdf(copro, ag, db))


def test_pv_mentionne_la_reduction_art22(db, copro_a):
    texte = _pv(db, copro_a)
    assert "Réduction art. 22" in texte
    assert "800 voix" in texte
    # Chiffres réduits : exprimés en voix, plus en millièmes
    assert "Pour : 400 voix" in texte


def test_pv_affiche_les_membres_en_art26(db, copro_a):
    assert "Membres pour : 2 / 3" in _pv(db, copro_a)


def test_pv_second_vote_suit_sa_resolution_et_hors_ordre_du_jour(db, copro_a):
    texte = _pv(db, copro_a)
    assert "Second vote immédiat de la résolution n° 1" in texte
    odj = texte.split("ORDRE DU JOUR")[1].split("RÉSOLUTIONS ET VOTES")[0]
    assert "second vote" not in odj
    corps = texte.split("RÉSOLUTIONS ET VOTES")[1]
    i_r1 = corps.index("Résolution 1 — Ravalement")
    i_sv = corps.index("Second vote immédiat")
    i_r2 = corps.index("Résolution 2")
    assert i_r1 < i_sv < i_r2
