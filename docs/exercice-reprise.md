# Exercice de reprise : perte du serveur, restauration depuis le drive, panne du drive

Une sauvegarde ne vaut que si elle se restaure. Cet exercice joue, sur de vrais serveurs, ce que ferait un
syndic le jour où son serveur disparaît. Il joue aussi ce qui se passe quand le drive de la copropriété tombe en panne.

- **Script** : [`backend/scripts/exercice_reprise.py`](../backend/scripts/exercice_reprise.py). Il n'utilise que la
  bibliothèque standard de Python ; ses réglages et ses commandes sont décrits en tête du fichier.
- **Joué le** 19 novembre 2026.
- **Version** : Proprietas 2026.11.032, image publiée sur GitHub.
- **Serveurs** : deux instances jetables, chacune avec son PostgreSQL 16, sur une machine de test.
- **Drive** : Nextcloud (WebDAV).

## Déroulé

| Étape | Ce qui est fait | Résultat |
|---|---|---|
| 1 | Serveur A : premier compte syndic, copropriété, 5 documents déposés sur le serveur (de 10 Ko à 2,5 Mo, libellés accentués) | OK |
| 2 | Drive branché, les 5 documents déplacés dessus, un 6e déposé directement sur le drive ; vérification du drive | 6 vérifiés, 0 introuvable |
| 3 | Sauvegarde chiffrée sur le drive (`Sauvegardes/Sauvegarde … .zip`), puis **serveur A détruit** (conteneurs et base) | OK |
| 4 | Serveur B neuf : archive récupérée sur le drive ; un mauvais mot de passe est refusé ; import | copropriété recréée, compte du syndic retrouvé, 6 documents « sur le drive » |
| 5 | Drive rebranché sur le même dossier ; chaque document relu et comparé à l'original (SHA-256) | **6 sur 6 identiques** ; la sauvegarde de A est listée sur B |
| 6 | **Nextcloud arrêté** : lecture, dépôt, sauvegarde, test du drive, passage du planificateur ; puis Nextcloud redémarré | messages ci-dessous ; retour à la normale sans intervention |

Bilan : **43 vérifications, aucun écart**.

La sauvegarde déposée sur le drive ne pèse que quelques kilo-octets, et c'est voulu. Les documents déjà rangés sur le drive n'y
sont pas recopiés : l'archive garde leur chemin, et ils sont relus sur le drive une fois celui-ci rebranché.

## Pendant la panne du drive

| Action | Réponse |
|---|---|
| Ouvrir un document | 503 : « Drive de la copropriété indisponible : Drive injoignable (ConnectError). » |
| Déposer un document | 503, même message : le document n'est pas enregistré, il faut le redéposer plus tard |
| Sauvegarder maintenant | 503 : « Sauvegarde impossible : Drive injoignable (ConnectError). » |
| Tester la connexion | « Drive injoignable (ConnectError). » |
| Sauvegarde automatique | l'échec et sa raison s'affichent dans Réglages → Sauvegarde et stockage |
| Le reste de l'application | disponible |

Après le redémarrage de Nextcloud, la lecture, le dépôt et la sauvegarde refonctionnent. L'erreur affichée
disparaît à la première sauvegarde réussie.

## Corrections faites à la suite (2026.11.033)

- **Personne n'était prévenu** quand la sauvegarde automatique échouait : il fallait ouvrir Réglages pour le
  voir. Désormais, les syndics reçoivent un e-mail au premier échec, puis un autre quand la sauvegarde
  refonctionne. Avec Google Drive, l'e-mail explique l'expiration à 7 jours de l'autorisation tant que
  l'application Google de l'instance est en mode « Test ».
- **Heures décalées** : le conteneur tournait en UTC. Toutes les heures affichées avaient donc une heure de
  retard sur Paris (deux en été) : noms des sauvegardes (« 23h31 » au lieu de 00h31), heure d'un échec, journal,
  e-mails. Un document déposé à 0 h 31 était même daté de la veille (« Factures/2026-11-18 … »). Le conteneur est
  maintenant à l'heure de Paris, et un autre fuseau se règle par `TZ=…` dans le `.env`.
- Les messages « Drive injoignable » ajoutent : « réessayez plus tard ; les fichiers déjà rangés ne sont pas
  perdus ».

## Ensuite (2026.11.034) : dépôts en attente du drive

L'exercice a montré qu'un document déposé pendant la panne était refusé. Une option d'instance permet
désormais de le garder sur le serveur et de le ranger sur le drive à son retour : `COPRO_DRIVE_ATTENTE_MO`,
place maximale en Mo. Elle est désactivée par défaut, pour les serveurs avec peu d'espace (voir le README).
Le script de l'exercice vérifie les deux comportements : dépôt refusé, ou dépôt en attente lisible puis rangé.

## Google Drive

Google Drive a été essayé sur le vrai service le 18 novembre 2026, sur la démo : connexion, dépôt, fichier
visible dans Google Drive. Cet essai a révélé un défaut, corrigé en 2026.11.031 : la reconnexion coupait
l'autorisation. Voir le [guide Google Drive](google-drive.md).
