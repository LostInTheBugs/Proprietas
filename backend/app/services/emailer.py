"""Envoi d'emails (convocations AG, tests SMTP) via smtplib (stdlib)."""
import smtplib
from datetime import date
from email.message import EmailMessage


class EmailError(Exception):
    pass


def envoyer_email(copro, destinataire: str, sujet: str, corps: str,
                  pieces_jointes: list[tuple[str, bytes, str]] | None = None) -> None:
    """Envoie un email via la config SMTP de la copropriété.

    pieces_jointes : liste de (nom_fichier, contenu_bytes, mime_type).
    Lève EmailError si la config est incomplète ou l'envoi échoue.
    """
    if not copro.smtp_host or not copro.email_expediteur:
        raise EmailError(
            "Configuration SMTP incomplète : renseignez le serveur et l'expéditeur "
            "dans Réglages → Envoi des emails."
        )
    msg = EmailMessage()
    msg["From"] = copro.email_expediteur
    msg["To"] = destinataire
    msg["Subject"] = sujet
    msg.set_content(corps, charset="utf-8")
    for nom, contenu, mime in (pieces_jointes or []):
        msg.add_attachment(contenu, maintype=mime.split("/")[0], subtype=mime.split("/")[1], filename=nom)

    port = copro.smtp_port or 587
    try:
        if port == 465:
            with smtplib.SMTP_SSL(copro.smtp_host, port, timeout=20) as server:
                _auth(server, copro)
                server.send_message(msg)
        else:
            with smtplib.SMTP(copro.smtp_host, port, timeout=20) as server:
                server.ehlo()
                if port == 587:
                    server.starttls()
                    server.ehlo()
                _auth(server, copro)
                server.send_message(msg)
    except EmailError:
        raise
    except Exception as e:
        raise EmailError(f"Échec de l'envoi : {e}") from e


def _auth(server, copro):
    if copro.smtp_user:
        try:
            server.login(copro.smtp_user, copro.smtp_password or "")
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
        "Ce fonds est obligatoire (art. 14-2 de la loi n°65-557) et servira au financement "
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


def convocation_texte(copro, ag, resolutions, syndic_nom: str) -> str:
    """Corps du message de convocation (texte brut)."""
    type_label = {
        "annuelle": "Assemblée Générale annuelle",
        "extraordinaire": "Assemblée Générale extraordinaire",
        "consultation_ecrite": "consultation écrite",
    }.get(ag.type_ag, "Assemblée Générale")

    lignes = [
        f"Bonjour,",
        "",
        f"Vous êtes convoqué(e) à {_article(type_label)} de la copropriété {copro.nom}.",
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
    lignes += ["", "Ordre du jour :"]
    if resolutions:
        for r in sorted(resolutions, key=lambda x: x.numero):
            lignes.append(f"  {r.numero}. {r.libelle}")
    else:
        lignes.append("  (à compléter)")
    lignes += [
        "",
        "Vous pouvez consulter les détails et répondre en ligne :",
        copro.frontend_url or "https://proprietas.cloudfr.net",
        "",
        "Cordialement,",
        syndic_nom or "Le syndic",
        f"Syndic bénévole — {copro.nom}",
    ]
    return "\n".join(lignes)


def _article(label: str) -> str:
    return "l'" + label if label.startswith("A") else "la " + label
