# Réunion en ligne : serveur Jitsi (en option)

Proprietas crée les salles de visioconférence des assemblées sur **meet.jit.si**, le service public et gratuit de
Jitsi. Rien n'est à installer.

Pour garder les réunions chez vous, vous pouvez lancer votre propre serveur Jitsi. Il est prêt dans
`docker-compose.yml` (profil `jitsi`), mais **éteint par défaut** : sans ce profil, rien de Jitsi ne tourne.

## 1. Lancer le serveur

Il faut :

- un nom de domaine pour la visio (exemple : `visio.exemple.fr`), pointé vers le serveur ;
- le port **UDP 10000** ouvert, et redirigé par la box vers ce serveur : c'est par là que passent le son et l'image ;
- deux mots de passe internes, qui ne servent qu'entre les conteneurs Jitsi.

Dans le fichier `.env`, à côté de `docker-compose.yml` :

```
JITSI_PUBLIC_URL=https://visio.exemple.fr
JICOFO_AUTH_PASSWORD=…        # openssl rand -hex 16
JVB_AUTH_PASSWORD=…           # openssl rand -hex 16
JITSI_ADVERTISE_IPS=…         # adresse IP publique du serveur (derrière une box)
```

Puis :

```
docker compose --profile jitsi up -d
```

Réglages facultatifs :

- `JITSI_HTTP_PORT` (8080 par défaut) et `JITSI_HTTPS_PORT` (8443) : ports de la page web ;
- `JITSI_JVB_PORT` (10000) : port UDP ;
- `JITSI_IMAGE_VERSION` (`stable`) : version des images, par exemple pour figer une version précise.

## 2. HTTPS

Le navigateur n'autorise la caméra et le micro qu'en HTTPS, avec un vrai certificat.

- **Avec le profil `internet` (Caddy)** : ajoutez au `Caddyfile` le bloc suivant, puis relancez Caddy. Caddy
  obtient le certificat tout seul.

  ```
  visio.exemple.fr {
  	reverse_proxy jitsi-web:80
  }
  ```

- **Avec un autre proxy** (Nginx, Traefik, proxy de la box…) : faites suivre `https://visio.exemple.fr` vers le
  port `JITSI_HTTP_PORT` du serveur.

## 3. Le choisir dans Proprietas

Dans **Réglages → Réunion en ligne**, saisissez `https://visio.exemple.fr`. Les prochaines salles créées par le
bouton « Créer une salle Jitsi » d'une AG y seront ouvertes. Laissez le champ vide pour revenir à meet.jit.si.

L'administrateur de l'instance peut aussi changer le serveur par défaut de toutes les copropriétés avec la
variable `COPRO_JITSI_URL`.

Un lien déjà envoyé aux copropriétaires reste sur l'ancien serveur. Recréez la salle (bouton « Nouvelle salle
Jitsi ») si besoin, puis renvoyez l'information.

## Arrêter le serveur

```
docker compose --profile jitsi stop jitsi-web jitsi-prosody jitsi-jicofo jitsi-jvb
```

Documentation complète de Jitsi : https://jitsi.github.io/handbook/docs/devops-guide/devops-guide-docker
