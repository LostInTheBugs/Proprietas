# Changelog

## 2026.10.023 — 2026-10-25

- Délais (code de procédure civile, art. 642) : la fin du délai de contestation du PV et celle du délai de 30 jours de la mise en demeure (art. 19-2) sont reportées au premier jour ouvrable lorsqu'elles tombent un samedi, un dimanche ou un jour férié, y compris les jours fériés propres à l'Alsace-Moselle (selon le code postal de la copropriété).

## 2026.10.022 — 2026-10-25

- Notifications (décret n° 67-223, art. 64 à 64-4, rédaction du décret n° 2025-1292) : la LRAR n'est admise que si le copropriétaire a demandé la voie postale, pour le PV comme pour la mise en demeure ; la demande prend effet le 9e jour suivant sa réception (le jour même si elle est faite en assemblée), date de réception saisie par le syndic.
- Mise en demeure : la remise contre récépissé n'est plus acceptée (art. 64-3) ; la signification par commissaire de justice la remplace. Une ancienne saisie « remise » ne fait plus courir le délai de l'article 19-2.
- Fonds de travaux avec PPT (art. 14-2-1) : la cotisation minimale est le plus élevé de 2,5 % du plan et de 5 % du budget, et non leur somme (écran Travaux corrigé).
- Limiteur de connexion : mémoire bornée (pas d'entrée créée par une vérification, purge des entrées expirées).

## 2026.10.021 — 2026-10-25

- Notification du PV : une lettre recommandée électronique est refusée pour un copropriétaire qui a demandé la voie postale (art. 42-1) ; badge et option grisée dans l'interface.
- Notification du PV : le mode d'une lettre dont l'envoi est saisi ne peut plus être changé (correction en deux temps : effacer la date d'envoi, puis changer le mode).

## 2026.10.020 — 2026-10-25

- Voie postale : chaque copropriétaire (ou le syndic pour lui) peut demander à recevoir ses notifications par lettre recommandée papier ; la lettre recommandée électronique reste la règle (art. 42-1). Demande datée et tracée (migration c0d1e2f3a4b5).
- Notification du procès-verbal : liste des copropriétaires opposants ou défaillants (art. 42 al. 2), mode LRE ou LRAR, saisie de l'envoi et de la première présentation, date limite d'un mois et fin indicative du délai de contestation. Une notification envoyée n'est jamais modifiée.

## 2026.10.019 — 2026-10-25

- Consultation écrite : procès-verbal dédié, signé par le syndic, indiquant le sens du vote de chaque copropriétaire, avec mention des écrits de vote annexés.
- Recouvrement : l'aperçu de l'article 19-2 est ventilé en parts distinctes (provisions à échoir, restes des exercices précédents approuvés, arriéré échu de l'exercice, exercices non approuvés) dont la somme est le solde du lot : plus de double compte.

## 2026.10.018 — 2026-10-25

- Applicateur de mises à jour : vérifie l'espace disque avant toute modification (1,5 Go en build, 0,5 Go en pull, réglable par PROPRIETAS_MIN_FREE_GB) et refuse avec un message clair s'il manque de la place.
- Applicateur : après une mise à jour réussie, supprime les images Docker orphelines et, en stratégie build, le cache de construction.
- Applicateur : les valeurs du .env entre guillemets sont lues comme par Docker Compose.

## 2026.10.017 — 2026-10-25

- Fonds de travaux : référence corrigée en article 14-2-1 de la loi du 10 juillet 1965 (PDF de mise en demeure, e-mail de situation du fonds).
- Notifications : la lettre recommandée électronique est la règle ; la LRAR papier est réservée au copropriétaire qui a demandé la voie postale (loi de 1965, art. 42-1 ; décret n° 67-223, art. 64-1). Textes de convocation, e-mail du PV et écran AG.

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
