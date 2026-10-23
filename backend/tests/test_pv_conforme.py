"""Procès-verbal conforme : décret n° 67-223 du 17 mars 1967, art. 17, et loi n° 65-557, art. 42 al. 2.

- Pour chaque résolution : noms et voix des opposants, des abstentionnistes et des défaillants.
- Les voix indiquées sont celles qui ont servi au décompte (réduction art. 22 comprise).
- « Fait à <ville>, le <date de l'AG> » (et non la date de génération du PDF).
- Signatures : président de séance, secrétaire, scrutateur(s).
- Mention légale : notification sous un mois, contestation sous deux mois (art. 42 al. 2).
"""
from datetime import date
from io import BytesIO

from pypdf import PdfReader

from app.core.security import hash_password
from app.models.ag import AG, Resolution, Vote
from app.models.lot import Lot
from app.models.user import User
from app.services.country_rules import calculer_statut_resolution
from app.services.pv_pdf import generer_pv_pdf, votants_nommes


def _texte(buf: BytesIO) -> str:
    reader = PdfReader(BytesIO(buf.getvalue()))
    # Les retours à la ligne du PDF coupent les phrases : on les remplace par des espaces.
    return " ".join((page.extract_text() or "").replace("\n", " ") for page in reader.pages)


def _user(db, copro, prenom, nom):
    u = User(email=f"{prenom.lower()}.{nom.lower()}@test.fr", password_hash=hash_password("x"),
             prenom=prenom, nom=nom, role="membre", copropriete_id=copro.id)
    db.add(u)
    db.flush()
    return u


def _ag(db, copro, votes_par_lot, tantiemes=(300, 100, 250, 200, 150), majorite="art24"):
    """5 lots : Dupont (lots 1 et 2), Martin (lot 3), Bernard (lot 4), lot 5 sans propriétaire."""
    dupont = _user(db, copro, "Jean", "Dupont")
    martin = _user(db, copro, "Claire", "Martin")
    bernard = _user(db, copro, "Luc", "Bernard")
    owners = (dupont, dupont, martin, bernard, None)
    lots = [Lot(copropriete_id=copro.id, numero=str(i + 1), tantiemes=t,
                proprietaire_id=o.id if o else None)
            for i, (t, o) in enumerate(zip(tantiemes, owners))]
    db.add_all(lots)
    ag = AG(copropriete_id=copro.id, date=date(2026, 11, 20))
    db.add(ag)
    db.flush()
    r = Resolution(ag_id=ag.id, numero=1, libelle="Ravalement", majorite=majorite)
    db.add(r)
    db.flush()
    for lot, v in zip(lots, votes_par_lot):
        if v is not None:
            db.add(Vote(resolution_id=r.id, lot_id=lot.id, voix=v))
    db.commit()
    db.refresh(ag)
    return ag, r, lots


def test_noms_et_voix_des_opposants_abstentionnistes_defaillants(db, copro_a):
    ag, r, lots = _ag(db, copro_a, ("pour", "pour", "contre", "abstention", None))
    noms = votants_nommes(r, lots, db)
    assert noms["contre"] == [("Martin Claire", ["3"], 250)]
    assert noms["abstention"] == [("Bernard Luc", ["4"], 200)]
    assert noms["defaillant"] == [("Propriétaire non renseigné", ["5"], 150)]

    texte = _texte(generer_pv_pdf(copro_a, ag, db))
    assert "Opposants : Martin Claire (lot 3) — 250‰" in texte
    assert "Abstentionnistes : Bernard Luc (lot 4) — 200‰" in texte
    assert "Défaillants : Propriétaire non renseigné (lot 5) — 150‰" in texte


def test_aucun_opposant(db, copro_a):
    ag, r, lots = _ag(db, copro_a, ("pour", "pour", "pour", "pour", "pour"))
    texte = _texte(generer_pv_pdf(copro_a, ag, db))
    assert "Opposants : aucun" in texte
    assert "Abstentionnistes : aucun" in texte
    assert "Défaillants : aucun" in texte


def test_vote_null_est_defaillant(db, copro_a):
    # « null » = case non cochée : le copropriétaire n'a pas voté.
    ag, r, lots = _ag(db, copro_a, ("pour", "pour", "pour", "null", "pour"))
    assert votants_nommes(r, lots, db)["defaillant"] == [("Bernard Luc", ["4"], 200)]


def test_membre_aux_votes_partages(db, copro_a):
    # Dupont vote « pour » avec le lot 1 et « contre » avec le lot 2 : seules les voix
    # du lot 2 sont des voix d'opposant ; il n'est pas défaillant.
    ag, r, lots = _ag(db, copro_a, ("pour", "contre", "pour", "pour", "pour"))
    noms = votants_nommes(r, lots, db)
    assert noms["contre"] == [("Dupont Jean", ["2"], 100)]
    assert noms["defaillant"] == []


def test_voix_reduites_art22(db, copro_a):
    # Dupont détient 700/1000 (> moitié) : ses voix sont réduites à 300 (art. 22 al. 2).
    ag, r, lots = _ag(db, copro_a, ("contre", "contre", "pour", "pour", None),
                      tantiemes=(600, 100, 100, 100, 100), majorite="art25")
    noms = votants_nommes(r, lots, db)
    voix_dupont = sum(v for _, _, v in noms["contre"])
    assert voix_dupont == 300
    texte = _texte(generer_pv_pdf(copro_a, ag, db))
    assert "Opposants : Dupont Jean (lots 1, 2) — 300 voix" in texte


def test_total_des_voix_nommees_egal_au_decompte(db, copro_a):
    # Les voix nommées sont exactement celles du décompte de la résolution.
    ag, r, lots = _ag(db, copro_a, ("contre", "pour", "contre", "abstention", "abstention"),
                      tantiemes=(500, 150, 133, 117, 100), majorite="art25")
    noms = votants_nommes(r, lots, db)
    res = calculer_statut_resolution(r, lots, r.votes)
    assert sum(v for _, _, v in noms["contre"]) == res["contre"]
    assert sum(v for _, _, v in noms["abstention"]) == res["abstention"]


def test_fait_a_la_ville_le_jour_de_l_ag(db, copro_a):
    copro_a.ville = "Thionville"
    db.commit()
    ag, r, lots = _ag(db, copro_a, ("pour",) * 5)
    texte = _texte(generer_pv_pdf(copro_a, ag, db))
    assert "Fait à Thionville, le 20 novembre 2026" in texte


def test_fait_le_sans_ville(db, copro_a):
    ag, r, lots = _ag(db, copro_a, ("pour",) * 5)
    texte = _texte(generer_pv_pdf(copro_a, ag, db))
    assert "Fait le 20 novembre 2026" in texte
    assert "Fait à ," not in texte


def test_signatures_et_mention_legale(db, copro_a):
    ag, r, lots = _ag(db, copro_a, ("pour",) * 5)
    texte = _texte(generer_pv_pdf(copro_a, ag, db))
    for qui in ("Le président de séance", "Le secrétaire", "Le ou les scrutateurs"):
        assert qui in texte
    assert "dans le délai d'un mois à compter de la tenue de l'assemblée" in texte
    assert "dans un délai de deux mois à compter de la notification" in texte
    assert "notifié à chaque copropriétaire dans un délai de deux mois" not in texte


def test_nom_avec_caracteres_speciaux(db, copro_a):
    # Une SCI « Dupont & Fils <Gestion> » ne doit pas casser la génération du PDF.
    ag, r, lots = _ag(db, copro_a, ("pour", "pour", "contre", "pour", "pour"))
    martin = db.get(User, lots[2].proprietaire_id)
    martin.nom, martin.prenom = "SCI Dupont & Fils <Gestion>", ""
    db.commit()
    texte = _texte(generer_pv_pdf(copro_a, ag, db))
    assert "Opposants : SCI Dupont & Fils <Gestion> (lot 3)" in texte
