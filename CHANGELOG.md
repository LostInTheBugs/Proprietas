# Changelog

## 2026.10.016 — 2026-10-24

- RGPD : mot de passe SMTP chiffré en base (clé dérivée de COPRO_SECRET_KEY ; les anciens mots de passe sont chiffrés au démarrage ; si la clé change, ressaisir le mot de passe).
- RGPD : purge quotidienne du journal d'audit et de l'IP et du navigateur de dernière connexion au-delà de COPRO_RETENTION_JOURNAL_MOIS (12 mois par défaut, 0 = jamais).
- RGPD : export « mes données » (droit d'accès) dans Réglages → Mes informations.
- Documentation : docs/rgpd.md et modèle d'information des copropriétaires.

## 2026.10.015 — 2026-10-24

- Approbation des comptes distincte de la clôture : date de l'AG saisie sur l'exercice (page Comptes) ou reportée par une résolution « approbation des comptes » adoptée (migration b9c0d1e2f3a4).
- Article 19-2 : les restes dus des exercices précédents ne sont retenus qu'après approbation des comptes ; les exercices non approuvés sont exclus et signalés. À faire : saisir la date d'approbation des exercices passés.
- Second vote (art. 25-1, 26-1) : l'objet de la résolution est conservé.

## 2026.10.014 — 2026-10-24

- Consultation écrite (art. 41-12) : réservée aux petites copropriétés (art. 41-8), décisions à l'unanimité des voix de tous les copropriétaires. Le budget prévisionnel et l'approbation des comptes en sont exclus (assemblée générale obligatoire).
- Résolutions : nouveau champ « Objet » (autre décision, budget prévisionnel, approbation des comptes), migration a8b9c0d1e2f3 ; les résolutions existantes reçoivent « autre ».

## 2026.10.013 — 2026-10-24

- Régime « petite copropriété » (art. 41-8) : seuls les lots de logements, bureaux et commerces sont comptés (caves, parkings et annexes exclus). Le critère du budget exige 3 exercices consécutifs budgétés : une copropriété sans historique n'est plus classée « petite » à tort. Détail affiché sur la page Comptes.
- Lots : nouveaux types maison, bureau et annexe ; type contrôlé à la saisie.

## 2026.10.012 — 2026-10-24

- Mise en demeure (art. 19-2) : le délai de 30 jours court à compter du lendemain de la première présentation (LRAR), de l'avis électronique (LRE) ou de la remise contre récépissé ; date à saisir dans le dossier (migration f3a4b5c6d7e8). Un e-mail simple n'est plus accepté comme mise en demeure ; la remise exige un récépissé. Intérêts au taux légal depuis la présentation.
- PDF de mise en demeure : point de départ du délai et cotisations du fonds de travaux.

## 2026.10.011 — 2026-10-24

- Assemblées : délai légal de convocation de 21 jours (art. 9 du décret n° 67-223) dans l'interface et pour l'e-mail automatique (migration : les AG à venir réglées sous 21 jours passent à 21).
- Les e-mails d'AG et de PV sont présentés comme une information : la convocation et la notification se font par lettre recommandée électronique, LRAR ou remise contre récépissé (décret n° 2025-1292). E-mail du PV corrigé (art. 42, al. 2).

## 2026.10.010 — 2026-10-24

- Documents : la limite de taille (COPRO_UPLOAD_MAX_MB) s'applique pendant la réception. Refus immédiat si la taille annoncée dépasse la limite ; sinon copie par bloc, sans jamais charger le fichier entier en mémoire.
- Tests de l'applicateur de mises à jour ignorés sous Windows (script réservé à l'hôte Linux).

## 2026.10.009 — 2026-10-24

- Lots : surface validée à la saisie (NaN, Infinity, négatif ou ≥ 100 000 m² refusés ; arrondi au centième de m²). Une valeur invalide déjà en base n'empêche plus l'affichage des lots.

## 2026.10.008 — 2026-10-24

- Un compte copropriétaire sans liaison reçoit une 404 au lieu de se voir créer une copropriété par une simple lecture (GET).
- Rapports de travail déplacés dans docs/rapports ; capture d'écran de la démo dans le README.

## 2026.10.007 — 2026-10-24

- Sécurité : le jeton de session n'est plus accepté dans l'URL (?token=) ; seuls l'en-tête Bearer et le cookie HttpOnly restent valables.

## 2026.10.006 — 2026-10-23

- Authentification : python-jose remplacé par PyJWT, passlib par bcrypt (bibliothèques maintenues). Sessions et mots de passe existants inchangés. Un hash illisible donne un refus (401) au lieu d'une erreur 500.

## 2026.10.005 — 2026-10-23

- Montants saisis : arrondis au centime (taux : 4 décimales) dès la validation, y compris sous SQLite ; 422 pour NaN, Infinity et valeurs hors limites (au lieu de 500).

## 2026.10.004 — 2026-10-22

- Image Docker publiée sur GHCR à chaque release ; stratégie « pull » de l'applicateur pour les petits serveurs (PROPRIETAS_UPDATE_STRATEGY=pull).

## 2026.10.003 — 2026-10-21

- PV conforme : noms et voix des opposants, abstentionnistes et défaillants (décret 1967, art. 17), date de l'AG, signatures président/secrétaire/scrutateurs, mention art. 42 al. 2 corrigée.
- Administrateurs de l'instance gérés dans Réglages (fin de COPRO_INSTANCE_ADMINS) ; migration d4e5f6a7b8c9.

## 2026.10.002 — 2026-10-21

- Système de mise à jour : version affichée dans l'interface, vérification des releases GitHub, mise à jour depuis Réglages → Mises à jour via l'applicateur de l'hôte (sauvegarde de la base avant chaque mise à jour).

## 2026.10.001 — 2026-10-20

### Montants monétaires (PR #12)
- Montants stockés en `Numeric(12,2)` et taux en `Numeric(7,4)` (migration `840f497d9a3c`, avec arrondi des données existantes).
- Calculs en `Decimal` de bout en bout, avec arrondi comptable ROUND_HALF_UP.
- Répartition par tantièmes au plus fort reste. Le fonds de travaux est calculé sur le total, puis réparti.

### Moteur de majorités (PR #13)
- Art. 22 al. 2 : réduction des voix du copropriétaire majoritaire.
- Art. 26 : double majorité (membres et 2/3 des voix).
- Passerelles art. 25-1 et 26-1 : second vote immédiat (API, interface, PV ; migration `c7a1e2b3d4f5`).
- Régime à 2 copropriétaires calculé sur les membres.

### Divers
- Fichiers `VERSION`, `CHANGELOG.md` et workflow de release automatique.
