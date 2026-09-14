#!/usr/bin/env python3
"""Seed de démonstration Proprietas.

Crée un compte démo + 2 copropriétés réalistes (lots, comptes copropriétaires,
AG, PV/votes, documents, carnet, travaux, relances). Idempotent : ne fait rien
si le compte démo existe déjà.

MODÈLE « ZÉRO FICHE » : les propriétaires sont des COMPTES UTILISATEURS (plus de
fiches « Lots & occupants ») — chaque copropriétaire de la démo a donc un compte,
mot de passe `demo123456` (utile pour tester la vue consultation).

Exécution en production (dans le conteneur backend) :
    sudo docker compose exec -T backend python /tmp/seed_demo.py
"""
from datetime import date, datetime
from io import BytesIO

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User, UserCopro
from app.models.copropriete import Copropriete
from app.models.lot import Lot
from app.models.exercice import Exercice, BudgetLine
from app.models.appel import AppelFonds, AppelLot
from app.models.mouvement import Mouvement
from app.models.ag import AG, Resolution, Vote
from app.models.invitation import Invitation
from app.models.document import Document
from app.models.carnet import Entretien
from app.models.travaux import Travaux
from app.models.relance import Relance

db = SessionLocal()
EMAIL_DEMO = "demo@proprietas.cloudfr.net"
MDP_DEMO = "demo123456"
FRONT_URL = "https://proprietas.cloudfr.net"


def r2(x):
    return round(x + 1e-9, 2)


def petit_pdf(titre: str, corps: str) -> bytes:
    """Génère un petit PDF de démonstration (reportlab)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from app.services.pdf_base import register_fonts
    register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm,
                            topMargin=20 * mm, bottomMargin=20 * mm)
    st_t = ParagraphStyle("t", fontName="DejaVu", fontSize=15, leading=19, spaceAfter=8)
    st_p = ParagraphStyle("p", fontName="DejaVu", fontSize=10, leading=14)
    doc.build([
        Paragraph(titre, st_t),
        Spacer(1, 4 * mm),
        Paragraph(corps, st_p),
    ])
    return buf.getvalue()


def main():
    if db.query(User).filter(User.email == EMAIL_DEMO).first():
        print("Démo déjà en place — rien à faire.")
        return

    # ------------------------------------------------------------------ user
    user = User(email=EMAIL_DEMO, password_hash=hash_password(MDP_DEMO),
                nom="Syndic de démonstration", role="syndic", is_demo=True)
    db.add(user)
    db.flush()

    def nouvelle_copro(nom, adresse, ville, cp, annee, principale):
        c = Copropriete(
            nom=nom, adresse=adresse, ville=ville, code_postal=cp,
            annee_construction=annee, regles_pays="FR", devise="EUR",
            fonds_travaux_actif=True, fonds_travaux_taux_pct=5.0,
            fonds_travaux_compte="Livret A « Fonds travaux »",
            compte_bancaire_separe="Compte séparé au nom du syndicat",
            frontend_url=FRONT_URL,
            relance_frequence="hebdo", relance_jour=5, relance_heure="09:00",
            relance_minimum=50.0, relance_auto=False,
            totp_policy="off",  # comptes démo : jamais de 2FA imposée
        )
        db.add(c)
        db.flush()
        db.add(UserCopro(user_id=user.id, copropriete_id=c.id, principale=principale))
        return c

    def compte_coproprietaire(copro, prenom, nom, email, telephone="", adresse=""):
        """Compte copropriétaire (modèle « zéro fiche ») — mdp demo123456."""
        u = User(email=email, password_hash=hash_password(MDP_DEMO),
                 prenom=prenom, nom=nom, role="membre", is_demo=True,
                 adresse=adresse, telephone=telephone, copropriete_id=copro.id)
        db.add(u)
        db.flush()
        db.add(UserCopro(user_id=u.id, copropriete_id=copro.id, principale=True))
        return u

    # ======================================================================
    # 1) RÉSIDENCE LES TILLEULS — copropriété principale (5 lots)
    # ======================================================================
    t = nouvelle_copro("Résidence Les Tilleuls", "12 rue des Lilas", "Paris",
                       "75011", 1932, principale=True)

    pers = {}
    for prenom, nom, email, tel in [
        ("Marie", "Dubois", "marie.dubois@example.com", "06 12 34 56 78"),
        ("Jean", "Martin", "jean.martin@example.com", "06 23 45 67 89"),
        ("Sophie", "Bernard", "sophie.bernard@example.com", "06 34 56 78 90"),
        ("Paul", "Petit", "paul.petit@example.com", "06 45 67 89 01"),
        ("SCI", "Les Lilas", "contact.sci-lilas@example.com", "01 42 00 11 22"),
    ]:
        # Adresse postale : sert à la mise en demeure (démo recouvrement sur Bernard).
        adresse = ""
        if nom == "Bernard":
            adresse = "9 rue de la Roquette, 75011 Paris"
        pers[nom] = compte_coproprietaire(t, prenom, nom, email, tel, adresse)

    # Occupation : "" = non renseigné | "occupant" | "loue" | "vacant". Aucun
    # nom de locataire (RGPD) — lot 1 = propriétaire occupant (compte de Marie).
    lots = [
        ("1", "Appartement T2", "appartement", 210, 48.0, "Dubois", "occupant"),
        ("2", "Appartement T3", "appartement", 230, 62.0, "Martin", ""),
        ("3", "Appartement T3", "appartement", 230, 65.0, "Bernard", "loue"),
        ("4", "Appartement T1", "appartement", 140, 32.0, "Petit", "loue"),
        ("5", "Local commercial", "commerce", 190, 55.0, "Les Lilas", "vacant"),
    ]
    lot_objs = []
    for num, desig, typ, tant, surf, prop, statut_occ in lots:
        l = Lot(copropriete_id=t.id, numero=num, designation=desig, type=typ,
                tantiemes=tant, surface_m2=surf,
                proprietaire_id=pers[prop].id,
                statut_occupation=statut_occ)
        db.add(l)
        db.flush()
        lot_objs.append(l)

    # --- Exercices 2024 / 2025 / 2026
    budgets = {
        2024: [("Chauffage commun", 2100), ("Eau froide", 1700), ("Électricité parties communes", 850),
               ("Assurance immeuble", 1050), ("Entretien espaces verts", 750), ("Petites réparations", 1100),
               ("Nettoyage parties communes", 1400), ("Provision fonds travaux", 1550)],
        2025: [("Chauffage commun", 2250), ("Eau froide", 1800), ("Électricité parties communes", 880),
               ("Assurance immeuble", 1120), ("Entretien espaces verts", 780), ("Petites réparations", 1150),
               ("Nettoyage parties communes", 1450), ("Provision fonds travaux", 1770)],
        2026: [("Chauffage commun", 2400), ("Eau froide", 1800), ("Électricité parties communes", 900),
               ("Assurance immeuble", 1100), ("Entretien espaces verts", 800), ("Petites réparations", 1200),
               ("Nettoyage parties communes", 1500), ("Provision fonds travaux", 2100)],
    }
    exercices = {}
    for annee, lignes in budgets.items():
        ex = Exercice(copropriete_id=t.id, annee=annee, cloture=(annee < 2026))
        db.add(ex)
        db.flush()
        for libelle, montant in lignes:
            db.add(BudgetLine(exercice_id=ex.id, libelle=libelle, montant=float(montant),
                              type_repartition="generale"))
        exercices[annee] = ex

    def creer_appel(ex, libelle, emis, echeance, total):
        """Appel de fonds réparti par tantièmes, FT 5 % inclus."""
        ft = r2(total * 0.05)
        appel = AppelFonds(exercice_id=ex.id, libelle=libelle, date_emission=emis,
                           date_echeance=echeance, montant_total=r2(total),
                           inclut_fonds_travaux=True, fonds_travaux_montant=ft)
        db.add(appel)
        db.flush()
        for lot in lot_objs:
            db.add(AppelLot(appel_id=appel.id, lot_id=lot.id,
                            montant_charges=r2((total - ft) * lot.tantiemes / 1000),
                            montant_fonds_travaux=r2(ft * lot.tantiemes / 1000)))
        db.flush()  # rend les parts visibles pour le lazy-load de appel.parts
        return appel

    def payer(appel, lot, date_paiement):
        """Enregistre le paiement complet d'un appel par un lot (charges + FT)."""
        part = next(p for p in appel.parts if p.lot_id == lot.id)
        db.add(Mouvement(copropriete_id=t.id, exercice_id=appel.exercice_id,
                         date=date_paiement, libelle=f"{appel.libelle} — lot {lot.numero}",
                         type="encaissement", categorie="charges",
                         montant=part.montant_charges, lot_id=lot.id, appel_id=appel.id))
        if part.montant_fonds_travaux > 0:
            db.add(Mouvement(copropriete_id=t.id, exercice_id=appel.exercice_id,
                             date=date_paiement, libelle=f"{appel.libelle} (fonds travaux) — lot {lot.numero}",
                             type="encaissement", categorie="fonds_travaux",
                             montant=part.montant_fonds_travaux, lot_id=lot.id, appel_id=appel.id))

    def depense(ex, jour, libelle, montant, categorie="charges"):
        db.add(Mouvement(copropriete_id=t.id, exercice_id=ex.id, date=jour,
                         libelle=libelle, type="depense", categorie=categorie,
                         montant=r2(montant), lot_id=None))

    # --- 2024 : 3 appels, tous payés
    a1 = creer_appel(exercices[2024], "Appel de fonds T1 2024", date(2024, 3, 5), date(2024, 3, 31), 3500.0)
    a2 = creer_appel(exercices[2024], "Appel de fonds T2 2024", date(2024, 6, 5), date(2024, 6, 30), 3500.0)
    a3 = creer_appel(exercices[2024], "Appel de fonds T3 2024", date(2024, 9, 5), date(2024, 9, 30), 3500.0)
    for appel in (a1, a2, a3):
        for lot in lot_objs:
            payer(appel, lot, appel.date_echeance)
    depense(exercices[2024], date(2024, 1, 15), "Prime d'assurance immeuble 2024", 1080.0)
    depense(exercices[2024], date(2024, 4, 10), "Électricité parties communes (S1)", 740.0)
    depense(exercices[2024], date(2024, 6, 20), "Réparation chasse d'eau hall", 350.0)
    depense(exercices[2024], date(2024, 7, 5), "Entretien espaces verts", 420.0)
    depense(exercices[2024], date(2024, 11, 12), "Nettoyage parties communes (S2)", 900.0)

    # --- 2025 : 3 appels, tous payés + porte d'entrée (fonds travaux)
    b1 = creer_appel(exercices[2025], "Appel de fonds T1 2025", date(2025, 3, 5), date(2025, 3, 31), 3733.33)
    b2 = creer_appel(exercices[2025], "Appel de fonds T2 2025", date(2025, 6, 5), date(2025, 6, 30), 3733.33)
    b3 = creer_appel(exercices[2025], "Appel de fonds T3 2025", date(2025, 9, 5), date(2025, 9, 30), 3733.34)
    for appel in (b1, b2, b3):
        for lot in lot_objs:
            payer(appel, lot, appel.date_echeance)
    depense(exercices[2025], date(2025, 1, 15), "Prime d'assurance immeuble 2025", 1120.0)
    depense(exercices[2025], date(2025, 4, 12), "Électricité parties communes (S1)", 780.0)
    depense(exercices[2025], date(2025, 6, 18), "Dépannage plomberie", 420.0)
    depense(exercices[2025], date(2025, 7, 8), "Entretien espaces verts", 460.0)
    depense(exercices[2025], date(2025, 9, 22), "Remplacement porte d'entrée (fonds travaux)", 2300.0, "fonds_travaux")

    # --- 2026 : T1 et T2 émis ; lots 1, 2, 4 à jour — lots 3 et 5 en retard sur T2
    c1 = creer_appel(exercices[2026], "Appel de fonds T1 2026", date(2026, 1, 5), date(2026, 1, 31), 2950.0)
    c2 = creer_appel(exercices[2026], "Appel de fonds T2 2026", date(2026, 4, 5), date(2026, 4, 30), 2950.0)
    for appel in (c1, c2):
        for lot in (lot_objs[0], lot_objs[1], lot_objs[3]):  # lots 1, 2, 4 à jour
            payer(appel, lot, appel.date_echeance)
    payer(c1, lot_objs[4], c1.date_echeance)  # SCI a payé T1
    payer(c1, lot_objs[2], c1.date_echeance)  # Bernard a payé T1
    # lots 3 (Bernard) et 5 (SCI) : T2 non payé → relances
    depense(exercices[2026], date(2026, 1, 15), "Prime d'assurance immeuble 2026", 1160.0)
    depense(exercices[2026], date(2026, 2, 10), "Remplacement interphone (fonds travaux)", 620.0, "fonds_travaux")
    depense(exercices[2026], date(2026, 3, 14), "Nettoyage parties communes (S1)", 260.0)
    depense(exercices[2026], date(2026, 4, 11), "Électricité parties communes (S1)", 410.0)
    depense(exercices[2026], date(2026, 5, 6), "Entretien espaces verts", 230.0)
    depense(exercices[2026], date(2026, 6, 17), "Dépannage plomberie", 180.0)

    # --- AG : 2024 et 2025 terminées (votes), 2026 convoquée (sans votes)
    def ag_avec_resolutions(d, heure, statut, resos):
        ag = AG(copropriete_id=t.id, date=d, heure=heure, type_ag="annuelle",
                statut=statut, lieu="Hall de l'immeuble, 12 rue des Lilas",
                rappel_jours=15, convocation_envoyee=(statut != "projet"))
        db.add(ag)
        db.flush()
        for i, (libelle, majorite, statut_r, votes) in enumerate(resos, 1):
            res = Resolution(ag_id=ag.id, numero=i, libelle=libelle, texte="",
                             majorite=majorite, statut=statut_r)
            db.add(res)
            db.flush()
            for lot, voix in votes:
                lot_id = lot.id if hasattr(lot, "id") else lot
                db.add(Vote(resolution_id=res.id, lot_id=lot_id, voix=voix))
        return ag

    ag_avec_resolutions(date(2024, 3, 14), "18:30", "terminee", [
        ("Approbation des comptes de l'exercice 2023", "art24", "adoptee",
         [(lot_objs[0].id, "pour"), (lot_objs[1].id, "pour"), (lot_objs[2].id, "abstention"),
          (lot_objs[3].id, "pour"), (lot_objs[4].id, "pour")]),
        ("Approbation du budget prévisionnel 2024", "art24", "adoptee",
         [(lot_objs[0].id, "pour"), (lot_objs[1].id, "pour"), (lot_objs[2].id, "pour"),
          (lot_objs[3].id, "pour"), (lot_objs[4].id, "pour")]),
        ("Nomination du syndic bénévole pour l'exercice 2024", "art25", "adoptee",
         [(lot_objs[0].id, "pour"), (lot_objs[1].id, "pour"), (lot_objs[2].id, "pour"),
          (lot_objs[3].id, "pour"), (lot_objs[4].id, "pour")]),
    ])
    ag_avec_resolutions(date(2025, 3, 20), "18:30", "terminee", [
        ("Approbation des comptes de l'exercice 2024", "art24", "adoptee",
         [(lot_objs[0].id, "pour"), (lot_objs[1].id, "pour"), (lot_objs[2].id, "abstention"),
          (lot_objs[3].id, "pour"), (lot_objs[4].id, "pour")]),
        ("Approbation du budget prévisionnel 2025", "art24", "adoptee",
         [(lot_objs[0].id, "pour"), (lot_objs[1].id, "pour"), (lot_objs[2].id, "pour"),
          (lot_objs[3].id, "pour"), (lot_objs[4].id, "pour")]),
        ("Approbation du plan pluriannuel de travaux (ravalement, isolation, chaudière)", "art26", "adoptee",
         [(lot_objs[0].id, "pour"), (lot_objs[1].id, "pour"), (lot_objs[2].id, "pour"),
          (lot_objs[3].id, "pour"), (lot_objs[4].id, "pour")]),
        ("Remplacement de la porte d'entrée (fonds travaux)", "art24", "adoptee",
         [(lot_objs[0].id, "pour"), (lot_objs[1].id, "pour"), (lot_objs[2].id, "pour"),
          (lot_objs[3].id, "pour"), (lot_objs[4].id, "pour")]),
    ])
    ag2026 = ag_avec_resolutions(date(2026, 9, 18), "18:30", "convoquee", [
        ("Approbation des comptes de l'exercice 2025", "art24", "a_voter", []),
        ("Approbation du budget prévisionnel 2027", "art24", "a_voter", []),
        ("Ravalement de façade — mise en concurrence (plan pluriannuel 2027-2029)", "art26", "a_voter", []),
    ])
    for p in pers.values():
        db.add(Invitation(ag_id=ag2026.id, personne_id=p.id,
                          date_envoi=datetime(2026, 9, 3, 9, 0), statut="envoye"))

    # --- Documents (vrais petits PDF de démonstration)
    from app.core.config import get_settings
    import os
    upload_dir = get_settings().upload_dir
    os.makedirs(upload_dir, exist_ok=True)
    for libelle, categorie, titre, corps in [
        ("Règlement de copropriété — extrait", "autre",
         "Règlement de copropriété",
         "Résidence Les Tilleuls, 12 rue des Lilas, 75011 Paris.<br/><br/>"
         "Extrait (document de démonstration) : répartition des charges générales "
         "selon les tantièmes de chaque lot, jouissance des parties communes, "
         "règles de stationnement dans la cour intérieure."),
        ("Devis ravalement de façade", "devis",
         "Devis — Ravalement de façade",
         "Entreprise Rénov'Façades SARL — 45 000,00 € TTC.<br/><br/>"
         "Nettoyage haute pression, traitement des fissures, deux couches de peinture, "
         "reprise des appuis de fenêtres. Durée estimée : 6 semaines. "
         "Offre valable 90 jours. (Document de démonstration.)"),
        ("Diagnostic amiante 2024", "diagnostic",
         "Diagnostic amiante — rapport 2024",
         "Rapport de repérage amiante réalisé le 12/03/2024 par DiagnoConseil.<br/><br/>"
         "Aucune présence d'amiante détectée dans les parties communes accessibles. "
         "Prochain repérage recommandé avant travaux de ravalement. (Document de démonstration.)"),
    ]:
        nom_stocke = f"demo_{categorie}_{libelle[:20]}.pdf".replace(" ", "_").replace("/", "_")
        with open(os.path.join(upload_dir, nom_stocke), "wb") as f:
            f.write(petit_pdf(titre, corps))
        db.add(Document(copropriete_id=t.id, categorie=categorie, libelle=libelle,
                        fichier=nom_stocke, date_ajout=date(2026, 6, 1)))

    # --- Carnet d'entretien
    for jour, typ, presta, cout, desc in [
        (date(2024, 10, 22), "Contrôle chaudière", "Chauffage Service 75", 180.0,
         "Contrôle annuel de la chaudière collective — rapport conforme."),
        (date(2025, 2, 15), "Ramonage", "Chauffage Service 75", 120.0,
         "Ramonage des conduits des parties communes."),
        (date(2025, 10, 20), "Contrôle chaudière", "Chauffage Service 75", 185.0,
         "Contrôle annuel de la chaudière collective — rapport conforme."),
        (date(2026, 2, 18), "Ramonage", "Chauffage Service 75", 130.0,
         "Ramonage des conduits des parties communes."),
        (date(2026, 6, 12), "Désinfection réservoir d'eau", "Aqua Pro", 240.0,
         "Désinfection du réservoir d'eau potable — prélèvements conformes."),
    ]:
        db.add(Entretien(copropriete_id=t.id, date=jour, type_intervention=typ,
                         prestataire=presta, cout=cout, lot_id=None, description=desc))

    # --- Plan pluriannuel de travaux
    for libelle, categorie, annee, montant in [
        ("Ravalement de façade", "facade", 2027, 45000.0),
        ("Isolation des combles", "toiture", 2028, 12000.0),
        ("Remplacement de la chaudière collective", "chauffage", 2029, 15000.0),
    ]:
        db.add(Travaux(copropriete_id=t.id, libelle=libelle, categorie=categorie,
                       annee=annee, montant=montant, statut="planifie"))

    # --- Relances envoyées (historique)
    for lot, pers_nom, montant in [
        (lot_objs[2], "Bernard", 678.51),
        (lot_objs[4], "Les Lilas", 560.51),
    ]:
        db.add(Relance(lot_id=lot.id, personne_id=pers[pers_nom].id,
                       date_envoi=datetime(2026, 6, 15, 9, 0), statut="envoye",
                       montant_du=montant, message=""))

    # ======================================================================
    # 2) RÉSIDENCE LES ACACIAS — 2e immeuble (sélecteur + vue consolidée)
    # ======================================================================
    ac = nouvelle_copro("Résidence Les Acacias", "8 avenue des Acacias", "Lyon",
                        "69003", 1975, principale=False)

    pers_a = {}
    for prenom, nom, email in [
        ("Karim", "Benali", "karim.benali@example.com"),
        ("Claire", "Fontaine", "claire.fontaine@example.com"),
        ("Enzo", "Rossi", "enzo.rossi@example.com"),
    ]:
        pers_a[nom] = compte_coproprietaire(ac, prenom, nom, email)

    lots_a = []
    for num, desig, tant, prop, statut_occ in [
        ("1", "Appartement T3", 340, "Benali", ""),
        ("2", "Appartement T2", 330, "Fontaine", "loue"),
        ("3", "Appartement T2", 330, "Rossi", "vacant"),
    ]:
        l = Lot(copropriete_id=ac.id, numero=num, designation=desig, type="appartement",
                tantiemes=tant, surface_m2=None, proprietaire_id=pers_a[prop].id,
                statut_occupation=statut_occ)
        db.add(l)
        db.flush()
        lots_a.append(l)

    ex_a = Exercice(copropriete_id=ac.id, annee=2026, cloture=False)
    db.add(ex_a)
    db.flush()
    for libelle, montant in [
        ("Chauffage commun", 1800), ("Eau froide", 1200), ("Électricité parties communes", 700),
        ("Assurance immeuble", 900), ("Entretien espaces verts", 1100), ("Petites réparations", 800),
        ("Provision fonds travaux", 1000),
    ]:
        db.add(BudgetLine(exercice_id=ex_a.id, libelle=libelle, montant=float(montant),
                          type_repartition="generale"))

    def creer_appel_a(ex, libelle, emis, echeance, total):
        ft = r2(total * 0.05)
        appel = AppelFonds(exercice_id=ex.id, libelle=libelle, date_emission=emis,
                           date_echeance=echeance, montant_total=r2(total),
                           inclut_fonds_travaux=True, fonds_travaux_montant=ft)
        db.add(appel)
        db.flush()
        for lot in lots_a:
            db.add(AppelLot(appel_id=appel.id, lot_id=lot.id,
                            montant_charges=r2((total - ft) * lot.tantiemes / 1000),
                            montant_fonds_travaux=r2(ft * lot.tantiemes / 1000)))
        db.flush()  # rend les parts visibles pour le lazy-load de appel.parts
        return appel

    def payer_a(appel, lot, date_paiement):
        part = next(p for p in appel.parts if p.lot_id == lot.id)
        db.add(Mouvement(copropriete_id=ac.id, exercice_id=appel.exercice_id,
                         date=date_paiement, libelle=f"{appel.libelle} — lot {lot.numero}",
                         type="encaissement", categorie="charges",
                         montant=part.montant_charges, lot_id=lot.id, appel_id=appel.id))
        if part.montant_fonds_travaux > 0:
            db.add(Mouvement(copropriete_id=ac.id, exercice_id=appel.exercice_id,
                             date=date_paiement, libelle=f"{appel.libelle} (fonds travaux) — lot {lot.numero}",
                             type="encaissement", categorie="fonds_travaux",
                             montant=part.montant_fonds_travaux, lot_id=lot.id, appel_id=appel.id))

    d1 = creer_appel_a(ex_a, "Appel de fonds T1 2026", date(2026, 1, 5), date(2026, 1, 31), 2500.0)
    d2 = creer_appel_a(ex_a, "Appel de fonds T2 2026", date(2026, 4, 5), date(2026, 4, 30), 2500.0)
    for appel in (d1, d2):
        for lot in lots_a[:2]:
            payer_a(appel, lot, appel.date_echeance)
    payer_a(d1, lots_a[2], d1.date_echeance)  # Rossi : T1 payé, T2 en retard
    db.add(Mouvement(copropriete_id=ac.id, exercice_id=ex_a.id, date=date(2026, 1, 15),
                     libelle="Prime d'assurance immeuble 2026", type="depense",
                     categorie="charges", montant=900.0, lot_id=None))
    db.add(Mouvement(copropriete_id=ac.id, exercice_id=ex_a.id, date=date(2026, 4, 12),
                     libelle="Électricité parties communes (S1)", type="depense",
                     categorie="charges", montant=350.0, lot_id=None))
    db.add(Mouvement(copropriete_id=ac.id, exercice_id=ex_a.id, date=date(2026, 5, 20),
                     libelle="Entretien espaces verts", type="depense",
                     categorie="charges", montant=280.0, lot_id=None))

    ag_ac = AG(copropriete_id=ac.id, date=date(2026, 11, 12), heure="19:00",
               type_ag="extraordinaire", statut="projet",
               lieu="Chez Mme Fontaine", rappel_jours=15, convocation_envoyee=False)
    db.add(ag_ac)
    db.flush()
    db.add(Resolution(ag_id=ag_ac.id, numero=1,
                      libelle="Travaux de rénovation de l'éclairage des parties communes",
                      texte="", majorite="art24", statut="a_voter"))

    db.add(Travaux(copropriete_id=ac.id, libelle="Rénovation éclairage parties communes",
                   categorie="electricite", annee=2027, montant=4500.0, statut="planifie"))
    db.add(Entretien(copropriete_id=ac.id, date=date(2026, 10, 8), type_intervention="Contrôle chaudière",
                     prestataire="Lyon Chauffage", cout=150.0, lot_id=None,
                     description="Contrôle annuel de la chaudière collective."))

    db.commit()
    print("Démo créée : demo@proprietas.cloudfr.net / demo123456")
    print("  - Résidence Les Tilleuls (Paris, 5 lots, comptes 2024-2026, AG, documents, PPT)")
    print("  - Résidence Les Acacias (Lyon, 3 lots)")
    print("  - Comptes copropriétaires (mot de passe demo123456) : marie.dubois, jean.martin,")
    print("    sophie.bernard, paul.petit, contact.sci-lilas, karim.benali, claire.fontaine, enzo.rossi")


if __name__ == "__main__":
    main()
