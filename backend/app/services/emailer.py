"""Envoi d'emails (convocations AG, tests SMTP) via smtplib (stdlib).

Réglages d'envoi : ceux de la copropriété si elle a saisi un serveur (Réglages → E-mails et relances),
sinon ceux de l'instance (COPRO_SMTP_*, COPRO_EMAIL_EXPEDITEUR). Jamais de mélange entre les deux.
"""
import smtplib
from datetime import date
from email.message import EmailMessage
from types import SimpleNamespace

from app.core.config import get_settings


class EmailError(Exception):
    pass


def config_smtp(copro) -> SimpleNamespace | None:
    """Réglages d'envoi effectifs pour cette copropriété, ou None s'il n'y en a pas de complets.

    - la copropriété a saisi un serveur : SES réglages, en entier (None s'il manque l'expéditeur) ;
    - sinon ceux de l'instance, s'ils ont un serveur et un expéditeur.
    `source` vaut « copropriete » ou « instance ». Le résultat ne contient aucun objet SQLAlchemy.
    """
    if getattr(copro, "smtp_host", ""):
        if not copro.email_expediteur:
            return None
        return SimpleNamespace(source=getattr(copro, "source", "copropriete"), smtp_host=copro.smtp_host,
                               smtp_port=copro.smtp_port, smtp_user=copro.smtp_user,
                               smtp_password=copro.smtp_password, email_expediteur=copro.email_expediteur)
    s = get_settings()
    if s.smtp_host and s.email_expediteur:
        return SimpleNamespace(source="instance", smtp_host=s.smtp_host, smtp_port=s.smtp_port,
                               smtp_user=s.smtp_user, smtp_password=s.smtp_password,
                               email_expediteur=s.email_expediteur)
    return None


def adresse_publique(copro) -> str:
    """Adresse de l'application à citer dans les e-mails : copropriété, sinon instance, sinon rien."""
    return (getattr(copro, "frontend_url", "") or get_settings().frontend_url or "").strip()


def envoyer_email(copro, destinataire: str, sujet: str, corps: str,
                  pieces_jointes: list[tuple[str, bytes, str]] | None = None) -> None:
    """Envoie un email avec les réglages de la copropriété, ou à défaut ceux de l'instance.

    pieces_jointes : liste de (nom_fichier, contenu_bytes, mime_type).
    Lève EmailError si la config est incomplète ou l'envoi échoue.
    """
    cfg = config_smtp(copro)
    if cfg is None:
        raise EmailError(
            "Configuration SMTP incomplète : renseignez le serveur et l'expéditeur "
            "dans Réglages → Envoi des emails."
        )
    msg = EmailMessage()
    msg["From"] = cfg.email_expediteur
    msg["To"] = destinataire
    msg["Subject"] = sujet
    msg.set_content(corps, charset="utf-8")
    for nom, contenu, mime in (pieces_jointes or []):
        msg.add_attachment(contenu, maintype=mime.split("/")[0], subtype=mime.split("/")[1], filename=nom)

    port = cfg.smtp_port or 587
    try:
        if port == 465:
            with smtplib.SMTP_SSL(cfg.smtp_host, port, timeout=20) as server:
                _auth(server, cfg)
                server.send_message(msg)
        else:
            with smtplib.SMTP(cfg.smtp_host, port, timeout=20) as server:
                server.ehlo()
                if port == 587:
                    server.starttls()
                    server.ehlo()
                _auth(server, cfg)
                server.send_message(msg)
    except EmailError:
        raise
    except Exception as e:
        raise EmailError(f"Échec de l'envoi : {e}") from e


def _auth(server, cfg):
    if cfg.smtp_user:
        try:
            server.login(cfg.smtp_user, cfg.smtp_password or "")
        except smtplib.SMTPAuthenticationError as e:
            raise EmailError(f"Authentification SMTP refusée ({e.smtp_code})") from e


def _date_fr(d) -> str:
    """Formatage de date en français (indépendant de la locale du serveur)."""
    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    mois = ["janvier", "février", "mars", "avril", "mai", "juin",
            "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    return f"{jours[d.weekday()]} {d.day} {mois[d.month - 1]} {d.year}"


def relance_texte(copro, lot_numero: str, personne_prenom: str, solde: float,
                  appels_charges: float, appels_fonds: float, encaisse: float,
                  syndic_nom: str) -> str:
    """Corps du message de relance d'impayé (texte brut)."""
    def fmt(v: float) -> str:
        return f"{v:,.2f} €".replace(",", " ").replace(".", ",")
    lignes = [
        f"Bonjour {personne_prenom},",
        "",
        f"Le solde de votre lot {lot_numero} s'élève à {fmt(solde)} au {_date_fr(date.today())} :",
        f"  • Appels de fonds (charges) : {fmt(appels_charges)}",
        f"  • Fonds de travaux : {fmt(appels_fonds)}",
        f"  • Encaissements reçus : {fmt(encaisse)}",
        "",
        "Merci de bien vouloir régulariser votre situation.",
    ]
    if copro.compte_bancaire_separe:
        lignes += [
            "",
            "Règlement par virement à l'ordre du syndicat des copropriétaires :",
            f"  {copro.compte_bancaire_separe}",
        ]
    lignes += [
        "",
        "N'hésitez pas à contacter le syndic pour toute question ou demande d'échéancier.",
        "",
        "Cordialement,",
        f"{syndic_nom} — Syndic bénévole de {copro.nom}",
    ]
    return "\n".join(lignes)


def situation_texte(copro, personne_prenom: str, lot_numero: str, solde_lot: float,
                    ft_encaisse: float, ft_depense: float, ft_encours: float,
                    objectif_ft: float, syndic_nom: str) -> str:
    """Email de situation du fonds de travaux envoyé aux copropriétaires."""
    lignes = [
        f"Bonjour {personne_prenom},",
        "",
        f"Voici la situation du fonds de travaux de la copropriété « {copro.nom} » :",
        "",
        f"  • Cotisations encaissées : {_fmt_eur(ft_encaisse)}",
        f"  • Dépenses financées par le fonds : {_fmt_eur(ft_depense)}",
        f"  • Encours du fonds de travaux : {_fmt_eur(ft_encours)}",
        f"  • Objectif annuel minimal (5 % du budget) : {_fmt_eur(objectif_ft)}",
        "",
        "Situation de votre lot :",
        f"  • Lot {lot_numero} — solde de votre compte de charges : {_fmt_eur(solde_lot)}",
        "",
        "Ce fonds est obligatoire (art. 14-2-1 de la loi n°65-557) et servira au financement "
        "des travaux prévus au plan pluriannuel de travaux.",
        "",
        f"Pour toute question, contactez le syndic ({syndic_nom}).",
        "",
        "Cordialement,",
        f"{syndic_nom}",
    ]
    return "\n".join(lignes)


def _fmt_eur(v: float) -> str:
    return f"{v:,.2f} €".replace(",", " ").replace(".", ",")


# Un e-mail simple n'est pas une notification au sens du décret n° 67-223 (art. 64 et s.,
# rédaction du décret n° 2025-1292 du 22/12/2025) : ces messages sont des INFORMATIONS.
# La voie électronique est la règle ; le papier, l'exception à la demande du copropriétaire
# (loi n° 65-557, art. 42-1 ; décret, art. 64-1).
# Une ligne, en bas du message (choix de Fred, 19/11/2026) : l'e-mail reste une information.
MENTION_CONVOCATION = (
    "Pour information : la convocation officielle vous parvient par lettre recommandée électronique "
    "(par défaut), ou par lettre recommandée papier si vous avez demandé la voie postale "
    "(loi n° 65-557, art. 42-1 ; décret n° 67-223, art. 9 et 64)."
)


def convocation_sujet(copro, ag) -> str:
    return (f"Information : {ag.type_ag.replace('_', ' ')} — {copro.nom} "
            f"({ag.date.strftime('%d/%m/%Y')})")


def pv_email_texte(copro, ag, syndic_nom: str) -> str:
    """Corps de l'e-mail accompagnant le PV (information, pas notification)."""
    type_label = {
        "annuelle": "l'assemblée générale annuelle",
        "extraordinaire": "l'assemblée générale extraordinaire",
        "consultation_ecrite": "la consultation écrite",
    }.get(ag.type_ag, "l'assemblée générale")
    return (
        f"Bonjour,\n\n"
        f"Veuillez trouver ci-joint, pour information, le procès-verbal de {type_label} "
        f"de la copropriété {copro.nom} du {_date_fr(ag.date)}.\n\n"
        f"Cet e-mail ne vaut pas notification. Le procès-verbal est notifié aux copropriétaires "
        f"opposants ou défaillants dans le mois qui suit l'assemblée, par lettre recommandée "
        f"électronique, ou par lettre recommandée papier pour ceux qui ont demandé la voie "
        f"postale. Cette notification fait courir le délai de contestation de "
        f"deux mois (loi n° 65-557 du 10 juillet 1965, art. 42, alinéa 2).\n\n"
        f"Cordialement,\n{syndic_nom or 'Le syndic'}"
    )


def convocation_texte(copro, ag, resolutions, syndic_nom: str, lien_confirmation: str = "") -> str:
    """Corps de l'e-mail d'INFORMATION sur l'assemblée (texte brut).

    `lien_confirmation` : lien personnel « J'ai bien reçu ce message » (vide : pas de lien).
    """
    type_label = {
        "annuelle": "Assemblée Générale annuelle",
        "extraordinaire": "Assemblée Générale extraordinaire",
        "consultation_ecrite": "consultation écrite",
    }.get(ag.type_ag, "Assemblée Générale")

    lignes = [
        f"Bonjour,",
        "",
        f"La copropriété {copro.nom} tiendra {_article(type_label)}.",
        "",
    ]
    if ag.type_ag == "consultation_ecrite":
        lignes.append("Cette consultation se déroule par écrit : vos réponses sont attendues "
                      "avant la date limite indiquée.")
    else:
        date_str = _date_fr(ag.date)
        heure = ag.heure or "à définir"
        lieu = ag.lieu or "à définir"
        lignes.append(f"Date : {date_str} à {heure}")
        lignes.append(f"Lieu : {lieu}")
        if getattr(ag, "lien_visio", ""):
            lignes.append(f"Participation possible en visioconférence : {ag.lien_visio}")
    lignes += ["", "Ordre du jour :"]
    if resolutions:
        for r in sorted(resolutions, key=lambda x: x.numero):
            lignes.append(f"  {r.numero}. {r.libelle}")
    else:
        lignes.append("  (à compléter)")
    url = adresse_publique(copro)
    if url:
        lignes += ["", "Vous pouvez consulter les détails et répondre en ligne :", url]
    if lien_confirmation:
        lignes += ["", "Merci de confirmer que vous avez bien reçu ce message, et d'indiquer si vous serez présent(e)"
                       + (", en visioconférence" if getattr(ag, "lien_visio", "") else "")
                       + ", absent(e) ou représenté(e) (pouvoir à un autre copropriétaire) :", lien_confirmation]
    lignes += [
        "",
        "Cordialement,",
        syndic_nom or "Le syndic",
        f"Syndic bénévole — {copro.nom}",
        "",
        MENTION_CONVOCATION,
    ]
    return "\n".join(lignes)


def _article(label: str) -> str:
    return "l'" + label if label.startswith("A") else "la " + label
