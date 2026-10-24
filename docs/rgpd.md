# Proprietas et le RGPD

Ce document décrit les données personnelles traitées par Proprietas, pourquoi elles le sont, combien de temps les garder et comment répondre aux demandes des personnes. Il sert de base au **registre des activités de traitement** (RGPD, art. 30) du syndicat des copropriétaires.

Ce n'est pas un avis juridique. Les durées proposées sont des choix raisonnables et motivés : le syndicat peut les ajuster. Le statut de chaque source est indiqué en fin de document.

## 1. Qui est responsable ?

| Rôle | Qui | Conséquence |
|---|---|---|
| **Responsable de traitement** | Le **syndicat des copropriétaires**, représenté par son syndic (professionnel ou bénévole) | Il décide des finalités, informe les personnes et répond à leurs demandes. |
| **Sous-traitant** (art. 28) | Toute personne qui **héberge ou administre l'instance pour le compte du syndicat** (par exemple un copropriétaire informaticien qui fait tourner le serveur, ou un hébergeur) | Un **contrat de sous-traitance** écrit est nécessaire : objet, durée, sécurité, confidentialité, sort des données en fin de contrat. |
| Éditeur du logiciel | Le projet Proprietas | Ne voit aucune donnée : chaque instance est autonome. Seule la vérification des mises à jour interroge l'API publique de GitHub (liste des versions), sans aucune donnée de la copropriété. |

Le syndic qui installe Proprietas pour sa propre copropriété n'a pas de sous-traitant pour l'application elle-même. L'hébergeur du serveur (VPS) reste un sous-traitant pour le stockage.

## 2. Données traitées

| Catégorie | Données (table) | Personnes |
|---|---|---|
| Identité et contact | nom, prénom, e-mail, adresse postale, téléphone (`users`) | copropriétaires, syndic |
| Lien avec les lots | lots détenus, tantièmes, **statut d'occupation** (« propriétaire occupant », « loué », « vacant ») (`lots`) | copropriétaires |
| Vie du syndicat | votes par lot, PV, convocations envoyées (`votes`, `resolutions`, `invitations`) | copropriétaires |
| Comptes | appels de fonds par lot, encaissements, soldes (`appels_lots`, `mouvements`) | copropriétaires |
| Recouvrement | relances, mises en demeure, dates de présentation, montants réclamés, actes de procédure (`relances`, `actes_recouvrement`) | copropriétaires débiteurs |
| Sécurité du compte | mot de passe haché (bcrypt), secret 2FA et codes de secours hachés, dernière connexion (date, IP, navigateur) (`users`) | tous les comptes |
| Journal d'audit | action, date, e-mail et nom de l'auteur, IP, navigateur (`audit_logs`) | tous les comptes |
| Prestataires | nom, téléphone, e-mail, adresse des contacts (`contacts`) | entreprises, artisans (souvent personnes morales) |
| Documents | fichiers déposés par le syndic (`uploads/`) | selon le contenu |

**Volontairement absent** :

- aucun nom de locataire. L'occupation est déclarée par le propriétaire, sans identité de l'occupant ;
- aucune donnée de santé, aucun numéro de sécurité sociale, aucun numéro de carte bancaire ;
- les impayés ne sont pas des données « sensibles » au sens de l'art. 9 du RGPD, mais ils sont **confidentiels** : seul le syndic y a accès dans l'application.

## 3. Finalités et bases légales (RGPD, art. 6)

| Finalité | Base légale |
|---|---|
| Tenir la liste des copropriétaires, convoquer et tenir les AG, établir et notifier les PV | **Obligation légale** (loi du 10 juillet 1965, décret du 17 mars 1967, dont art. 32 pour la liste des copropriétaires) |
| Appeler les charges et provisions, tenir les comptes du syndicat | **Obligation légale** |
| Recouvrer les impayés (relances, mise en demeure, art. 19-2, procédure) | **Obligation légale** et **intérêt légitime** du syndicat à recouvrer ses créances |
| Accès en ligne aux documents de la copropriété | **Obligation légale** pour un syndic professionnel (loi de 1965, art. 18) ; intérêt légitime sinon |
| Sécurité des comptes et journal d'audit | **Intérêt légitime** (sécurité du service, preuve) et obligation de sécurité (RGPD, art. 32) |
| Déclaration d'occupation des lots | **Intérêt légitime** (connaître les occupants pour la gestion de l'immeuble), sans nom du locataire |
| E-mails d'information (rappels d'AG, avis divers) | **Intérêt légitime** ; ce ne sont **pas** des notifications légales (voir README) |

Aucune donnée n'est utilisée pour de la prospection commerciale, ni transmise à des tiers en dehors des cas prévus par la loi.

## 4. Qui voit quoi (destinataires)

- **Syndic** : tout, pour sa copropriété uniquement (isolement testé entre copropriétés).
- **Copropriétaire (membre)** : ses propres données et ses lots, les documents de la copropriété, les AG et leurs résultats. Il **ne voit pas** le recouvrement des autres.
- **Administrateur de l'instance** : gère les comptes et les mises à jour ; il a techniquement accès au serveur, d'où la nécessité d'un contrat de sous-traitance s'il n'est pas le syndic.
- **Tiers** : commissaire de justice, avocat, tribunal, prestataire de recommandé électronique, uniquement pour les besoins d'une procédure ou d'une notification.
- **Prestataire d'e-mail (SMTP)** configuré par le syndic : il voit les e-mails envoyés.

## 5. Durées de conservation

Ces durées sont **proposées**. Proprietas purge **automatiquement** le journal d'audit et les informations de dernière connexion (voir ci-dessous) ; pour le reste, le syndic applique ces durées lors de revues périodiques, par exemple chaque année après l'AG.

| Données | Durée proposée | Justification |
|---|---|---|
| Compte d'un copropriétaire en place | Tant qu'il est copropriétaire | Nécessaire à la gestion |
| Compte d'un **ancien** copropriétaire | Suppression après la vente et le solde de son compte (quelques mois) | Plus de finalité. La suppression du compte efface nom et contact ; l'historique reste rattaché au **lot** (« zéro fiche ») |
| Dossier de recouvrement (relances, mises en demeure, actes) | **5 ans** après le paiement complet, ou jusqu'à la fin de la procédure | Prescription des actions personnelles relatives à la copropriété : 5 ans (loi de 1965, art. 42, renvoi à l'art. 2224 du code civil) |
| Pièces comptables du syndicat | **10 ans** | Usage aligné sur l'obligation de conservation des documents comptables (code de commerce, art. L123-22, par analogie) |
| PV d'AG, registre, résultats des votes | **Durée de vie du syndicat** | Archives du syndicat, transmises de syndic en syndic |
| Journal d'audit et dernières connexions (IP, navigateur) | **12 mois** par défaut, purge automatique quotidienne (`COPRO_RETENTION_JOURNAL_MOIS`, 0 = jamais) | Recommandation de la CNIL pour la journalisation (6 mois à 1 an) |
| Sauvegardes de la base (`data/backups/`) | Les 10 dernières (rotation automatique) | Une donnée supprimée peut rester dans une sauvegarde jusqu'à sa rotation : le dire à la personne qui demande l'effacement |
| Fichiers déposés | Selon leur nature (contrat : durée du contrat + 5 ans ; diagnostic : durée de validité) | À trier lors de la revue annuelle |

## 6. Droits des personnes

| Droit | Comment y répondre aujourd'hui |
|---|---|
| **Accès** (art. 15) | La personne télécharge elle-même ses données (Réglages → Mes informations → « Télécharger mes données », fichier JSON : profil, lots, décomptes, votes, courriers reçus, actes de recouvrement la concernant, journal de ses actions). Le syndic complète si besoin (PV, documents). |
| **Rectification** (art. 16) | La personne corrige elle-même son profil (Réglages). Le syndic corrige le reste. |
| **Effacement** (art. 17) | Suppression du compte par le syndic. Limite : les données nécessaires à une obligation légale (comptes, PV) ou au recouvrement en cours sont conservées, détachées du nom quand c'est possible. |
| **Opposition** (art. 21) | Possible pour les traitements fondés sur l'intérêt légitime (e-mails d'information, déclaration d'occupation), pas pour les obligations légales. |
| **Limitation, portabilité** | Au cas par cas ; la portabilité ne s'applique pas aux traitements fondés sur une obligation légale. |

Délai de réponse : **un mois** (RGPD, art. 12). En cas de désaccord, la personne peut saisir la **CNIL**.

## 7. Sécurité (RGPD, art. 32)

En place :

- mots de passe hachés (bcrypt) ;
- double authentification (TOTP), imposable par copropriété ;
- session en cookie `HttpOnly`, jamais de jeton dans l'URL ;
- isolement des copropriétés vérifié par les tests ;
- journal d'audit des actions sensibles (connexion, 2FA, exports, recouvrement) ;
- limite de taille des fichiers déposés ;
- HTTPS via le proxy (Caddy ou Traefik) ;
- mot de passe SMTP chiffré en base (clé dérivée de `COPRO_SECRET_KEY`) ;
- mises à jour par version publiée (tag) et sauvegarde automatique de la base avant chaque mise à jour.

## 8. Écarts connus et pistes

Corrigés en 2026.10.016 :

- purge automatique quotidienne du journal d'audit et de l'IP et du navigateur de dernière connexion, au-delà de `COPRO_RETENTION_JOURNAL_MOIS` (12 mois par défaut) ;
- export « mes données » (droit d'accès) depuis Réglages ;
- mot de passe SMTP chiffré en base ; les anciens mots de passe en clair sont chiffrés au démarrage. **Si `COPRO_SECRET_KEY` change, le mot de passe SMTP devient illisible et doit être ressaisi** (comme la 2FA).

Restent :

- **Le journal d'audit survit à la suppression d'un compte**, avec l'e-mail et le nom de l'auteur, jusqu'à sa purge (12 mois). C'est voulu (preuve).
- **Ancienne table `personnes`** (avant le modèle « zéro fiche ») : plus utilisée par l'interface. À vider sur les instances anciennes après vérification.
- **Sauvegardes** : une donnée purgée ou supprimée reste dans les 10 dernières sauvegardes jusqu'à leur rotation.

## 9. Modèle d'information des copropriétaires

Voir `docs/information-coproprietaires.md` : texte à adapter, puis à remettre (ou à joindre à la convocation de l'AG) et à publier dans les documents de la copropriété.

## Sources

**Réellement consultées (24/10/2026)** :

- CNIL, « La gestion des données personnelles au sein d'une copropriété » (cnil.fr) : responsabilité du syndic, accès du conseil syndical (art. 21), extranet sécurisé (art. 18), liste des copropriétaires (décret de 1967, art. 32), obligation d'informer sur la finalité, la durée de conservation et les droits.
- donneespersonnelles.fr, « RGPD et syndic de copropriété » : les impayés ne relèvent pas à eux seuls des données sensibles (art. 9).

**Textes de référence (non consultés directement : à vérifier sur Légifrance)** :

- RGPD, art. 6, 12, 13, 15 à 21, 28, 30 et 32.
- Loi n° 65-557 du 10 juillet 1965, art. 18, 21 et 42 ; code civil, art. 2224 (prescription de 5 ans).
- Décret n° 67-223 du 17 mars 1967, art. 32 et 33 (liste des copropriétaires, archives du syndicat).
- Code de commerce, art. L123-22 (conservation des documents comptables pendant 10 ans), appliqué ici par analogie.
- CNIL, recommandation sur la journalisation (durée de 6 mois à 1 an).
