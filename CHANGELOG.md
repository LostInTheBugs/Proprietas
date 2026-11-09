# Changelog

## 2026.11.017 — 2026-11-09

- Historique : chaque état peut porter le solde bancaire du compte du syndicat et celui du compte du fonds de travaux au 31 décembre. Entre deux états, solde de départ + encaissements − dépenses saisis est comparé à la banque (avertissement en cas d'écart, sans bloquer). La trésorerie affichée part du solde de la base. Migration b6c7d8e9f0a1.

## 2026.11.016 — 2026-11-09

- Historique : les lots non séparables (cave, garage rattachés) sont contrôlés par ensemble ; un copropriétaire qui paie tout sur son appartement ne crée plus d'écart entre l'appartement et la cave. « Une ligne par lot » ne prépare qu'une ligne par ensemble.

## 2026.11.015 — 2026-11-09

- Mises à jour : après un retour arrière, l'application automatique ne réinstalle plus la version quittée (elle reprend avec la version suivante, ou dès une mise à jour manuelle). Si une mise à jour a été faite par un ancien applicateur, la version précédente proposée est corrigée.

## 2026.11.014 — 2026-11-09

- Mises à jour : le serveur garde la nouvelle version et la précédente, les plus anciennes sont supprimées (place disque). Dans Réglages → Serveur, l'administrateur peut revenir à la version précédente (sauvegarde de la base et annulation des migrations plus récentes, retour automatique en cas d'échec) ou ne pas la conserver.

## 2026.11.013 — 2026-11-09

- Comptes : filtres (libellé, type, lot, catégorie, contrat, montant), colonnes Type et Contrat, tri sur chaque colonne ; sélection de plusieurs mouvements pour changer d'un coup l'exercice, le type, la catégorie ou le contrat.
- Sauvegarde : mot de passe facultatif (archive chiffrée AES-256, lisible avec 7-Zip) ; par défaut sans données personnelles (comptes « Compte 1 », « Compte 2 »… à compléter après l'import) ni fichiers ; données personnelles et fichiers seulement avec un mot de passe.
- Réglages : la page est découpée en onglets.

## 2026.11.012 — 2026-11-09

- Réglages : carte « Espace de stockage ». Le syndic voit la place prise par les documents de la copropriété ; l'administrateur de l'instance voit aussi le disque du serveur (utilisé, libre), la taille de la base et les documents de toute l'instance (stockage S3 : espace utilisé seulement).
- Publication : seule la dernière release et la dernière image restent sur GitHub (les tags git sont conservés). Les notes de release reprennent les 10 versions précédentes.

## 2026.11.011 — 2026-11-09

- Sauvegarde d'une copropriété (Réglages, syndic) : téléchargement d'une archive ZIP contenant toutes les données de la copropriété, ses comptes et les fichiers des documents ; import de cette archive, sur ce serveur ou un autre, en nouvelle copropriété (comptes existants réutilisés, sinon recréés avec leur mot de passe ; 2FA à réactiver si la clé du serveur diffère). Limite COPRO_IMPORT_MAX_MB (500 Mo par défaut).

## 2026.11.010 — 2026-11-09

- Mouvements : un mouvement peut être rattaché à un contrat et à une facture (un document existant, ou un nouveau fichier joint depuis le formulaire, rangé dans Documents). La liste des mouvements affiche le contrat et le lien vers la facture ; la page Contrats indique ce qui a été payé dans l'année pour chaque contrat. Migration a5b6c7d8e9f0.

## 2026.11.009 — 2026-11-09

- Lots non séparables : dans « Lots & occupants », une cave ou un garage peut être rattaché à son lot principal. L'ensemble a le même propriétaire et se suit comme une seule unité : tableau de bord, recouvrement (un dossier, une mise en demeure), relances, paiements et quittances. Un lot sans rattachement reste séparé. Migration f4a5b6c7d8e9.
- Quittances : seuls les paiements de l'exercice y figurent.

## 2026.11.008 — 2026-11-09

- Comptes : l'exercice d'un mouvement se choisit dans le formulaire (en création, il suit l'année de la date) et se corrige en modification. Les mouvements datés d'une autre année que l'exercice affiché sont signalés, et un bouton les déplace vers l'exercice de leur année. Chaque changement est inscrit au journal d'audit. Une dépense ne peut pas quitter ni rejoindre un exercice dont les charges sont déjà régularisées.

## 2026.11.007 — 2026-11-09

- Avances sur charges et sur travaux : un encaissement de catégorie « Fonds de travaux » (ou « Travaux ») ne paie que la part fonds de travaux des appels, et son excédent reste une avance travaux, jamais utilisée pour des charges. Les autres encaissements paient d'abord les charges. Le dossier de recouvrement affiche le dû et l'avance pour chaque nature. Dans « Paiement copropriétaire », chaque lot reçoit une part charges et une part travaux. Rien ne change pour les paiements déjà saisis en « Charges ».

## 2026.11.006 — 2026-11-09

- Comptes : bouton « Paiement copropriétaire » pour un virement qui couvre tous les lots d'un copropriétaire. L'application propose la répartition (les sommes dues les plus anciennes d'abord, l'excédent en avance sur le lot principal), le syndic peut la corriger, puis un encaissement est enregistré pour chaque lot. Chaque paiement est inscrit au journal d'audit.

## 2026.11.005 — 2026-11-09

- Comptes : bouton « Modifier » sur les mouvements (date, libellé, type, catégorie, montant, lot) et sur les lignes de budget ; chaque modification d'un mouvement est inscrite au journal d'audit, avec l'avant et l'après. Le formulaire de mouvement propose désormais « Dépense » par défaut. Type, catégorie, lot et appel sont contrôlés à la saisie.

## 2026.11.004 — 2026-11-09

- Historique : import CSV d'un état au 31 décembre (créé en brouillon), d'appels de fonds ou de paiements. Vérification préalable avec les erreurs par numéro de ligne, refus en bloc à la moindre erreur, et un fichier importé deux fois ne compte jamais double. Séparateur « ; » ou « , », montants à la française, fichiers UTF-8 ou Excel (Windows-1252).

## 2026.11.003 — 2026-11-09

- Reprise de l'historique (menu Historique, syndic) : saisie de ce que chaque copropriétaire devait au 
  31 décembre, par lot et par exercice d'origine (négatif = crédit). L'état validé le plus ancien sert de 
  base : il crée les appels « Reprise de solde », et les appels et encaissements datés jusqu'à sa date 
  n'entrent plus dans les soldes. Les états plus récents sont des points de contrôle, comparés lot par lot ; 
  on peut remonter d'année en année. Migration e2f3a4b5c6d7.
- Soldes par lot calculés en un seul endroit (soldes des lots, relances, comptes, compte de gestion, 
  rapport annuel).

## 2026.11.002 — 2026-11-05

- Stockage S3 : compatibilité Clever Cloud Cellar et autres services compatibles S3 hors AWS (issue #42). L'application refusait de démarrer avec l'erreur MissingContentLength : les fichiers partent désormais avec un Content-Length, sans encodage aws-chunked.

## 2026.11.001 — 2026-11-04

- Stockage des documents sur S3 (issue #11) : COPRO_STOCKAGE=s3 envoie les documents dans un bucket compatible S3 (AWS, Clever Cloud Cellar, OVH, Scaleway, MinIO…), configuré par les variables COPRO_S3_*. Le mode local reste le défaut : rien à faire sur les serveurs existants.
- Stockage vérifié au démarrage : un bucket absent, de mauvais identifiants ou un dossier en lecture seule empêchent de démarrer, avec un message explicite.
- Commande python -m app.cli.migrer_stockage pour copier les documents existants (local vers S3 ou inverse, --simulation ; la source n'est jamais supprimée). Procédure dans le README, section « Stockage des documents ».

## 2026.10.024 — 2026-10-25

- Régularisation des charges (loi du 10 juillet 1965, art. 14-1 ; décret du 17 mars 1967, art. 6-2, 3°) : une fois les comptes d'un exercice approuvés, la page Comptes compare par lot les provisions appelées aux charges réelles et enregistre un appel de régularisation (complément à payer ou trop-perçu crédité au copropriétaire actuel). Le fonds de travaux n'est pas régularisé. Migration d1e2f3a4b5c6.

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
