# Proprietas

<img src="frontend/public/proprietas-lockup.png" alt="Proprietas — Data Sovereignty" width="170">

> Anciennement **CoproApp**, renommée **Proprietas** en septembre 2026 (nouvelle identité
> visuelle ; le dépôt GitHub devient `LostInTheBugs/Proprietas`, les anciennes URLs redirigent).
> Version courante : **2026.09.005**.

Gestion de copropriété pour syndic bénévole, conçue pour le régime « petite copropriété »
français (art. 41-8 de la loi du 10 juillet 1965, issu de l'ordonnance n° 2019-1101 :
**≤ 5 lots** à usage de logements, bureaux ou commerces, **ou** budget prévisionnel moyen
**< 15 000 €**/an) et **utilisable sans limite de lots** — 12 lots, 15 lots ou plus :
comptabilité simplifiée, consultation écrite, majorités de vote automatiques.

## 🎮 Démo

**https://proprietas.cloudfr.net** (anciennement https://copro.cloudfr.net, conservé) —
un compte de démonstration est préconfiguré avec
deux copropriétés complètes (Paris : 5 lots, comptes 2024-2026, AG + PV, documents,
plan pluriannuel de travaux ; Lyon : 3 lots) :

| Champ | Valeur |
|-------|--------|
| Email | `demo@proprietas.cloudfr.net` |
| Mot de passe | `demo123456` |

Le compte démo ne bloque pas l'inscription : le premier compte réel peut toujours
se créer normalement depuis la page de connexion.

## Fonctionnalités

- **Immeuble & lots** : lots, tantièmes (millièmes), propriétaires, locataires
- **Comptabilité simplifiée** : budget prévisionnel, appels de fonds automatiques par tantièmes,
  encaissements / dépenses, solde par lot, état daté, quittances
- **Fonds de travaux** : taux configurable (min. légal 5 %), suivi dédié
- **Recouvrement des impayés** : décompte détaillé par provision (imputation FIFO, échu / à
  échoir), relances email, **mise en demeure générée** (PDF), suivi du délai de 30 jours,
  **article 19-2** (exigibilité immédiate des provisions), intérêts au taux légal, frais,
  étapes amiables et judiciaires
- **Assemblées générales** : convocations, résolutions, moteur de majorités légal
  (art. 24 / 25 / 26, unanimité, régime 2 copropriétaires), procès-verbaux
- **Consultation écrite** (régime petite copropriété, unanimité)
- **Documents** : contrats, devis, factures, diagnostics (stockage local)
- **Contacts** : annuaire des entreprises, fournisseurs et artisans (téléphone, email,
  adresse, site web), recherche, catégories
- **Contrats** : énergie (EDF…), assurance copro, entretien — montant, période,
  renouvellement automatique, fournisseur lié, **échéances suivies automatiquement**
  (alertes J-60, badges Expiré / Expire bientôt, tri par urgence)
- **Carnet d'entretien** : interventions, prestataires, coûts
- **Exports** : registre des copropriétés, compte de gestion annuel
- **Multi-copropriétés** : un compte, plusieurs immeubles isolés, vue consolidée
- **Sécurité** : double authentification TOTP (compatible FreeOTP, Aegis, Google
  Authenticator…), codes de secours, réinitialisation assistée par le syndic,
  journal d'audit, alertes email de connexion
- **Thème clair / sombre** : au choix par compte (Réglages → Apparence) — clair, sombre
  ou système (suit l'appareil), appliqué dès le chargement sans clignotement
- **Multi-pays** : module de règles par pays (France en V1, extensible)

## Stack

- Backend : FastAPI + SQLAlchemy + JWT (Python 3.11)
- Frontend : React + TypeScript + Vite + Tailwind
- Base de données : PostgreSQL (prod) / SQLite (dev)
- Déploiement : Docker Compose + Caddy (TLS auto) — hébergé sur un serveur dédié, derrière Cloudflare

## Développement local

```bash
# Backend (port 8000)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head            # crée/met à jour le schéma (SQLite dev)
uvicorn app.main:app --reload --port 8000

# Frontend (port 5173)
cd frontend
npm install
npm run dev
```

Premier lancement : créer le compte syndic via `POST /api/auth/register` (ouvert tant qu'aucun utilisateur n'existe).

## Sécurité

- **`COPRO_SECRET_KEY` obligatoire hors dev** : le backend refuse de démarrer
  (hors base SQLite) si la clé de signature JWT n'a pas été définie —
  la valeur par défaut `change-me` est publique et permettrait de forger des
  tokens. Génération : `python -c "import secrets; print(secrets.token_hex(32))"`.
- **Rate limiting sur `/api/auth/login`** : 5 tentatives échouées par email et
  par IP sur 15 minutes, puis `429` (limiteur en mémoire, adapté à une instance
  mono-serveur).
- **Session par cookie `HttpOnly`** : le jeton de session n'est pas accessible au
  JavaScript (rien dans `localStorage`), posé à la connexion — `SameSite=Lax`,
  `Secure` derrière HTTPS, supprimé au logout. Le header `Bearer` et `?token=`
  restent acceptés pour l'API/CLI (scripts, tests) ; les jetons hérités des
  versions précédentes sont migrés automatiquement en cookie au premier
  chargement (aucune reconnexion nécessaire).
- **Upload de documents** : plafond configurable `COPRO_UPLOAD_MAX_MB` (défaut
  25 Mo, `413` au-delà) et liste blanche d'extensions
  (`.pdf .jpg .jpeg .png .doc .docx .xls .xlsx .odt .ods`, `400` sinon).
- **CORS** : liste d'origines configurable `COPRO_CORS_ORIGINS` (JSON).
  Vide en production — le frontend est servi par le même backend. En dev
  (SQLite), `http://localhost:5173` est autorisé automatiquement.
- **Isolation multi-copropriétés** : tout accès par identifiant est scopé à la
  copropriété active du token (404 si l'objet appartient à une autre copro).
- **Double authentification (TOTP, RFC 6238)** : par compte, sans dépendance
  externe — compatible avec toute application d'authentification (FreeOTP, Aegis,
  Google Authenticator…). Codes de secours à usage unique (affichés une seule fois),
  désactivation protégée par mot de passe + code, réinitialisation assistée par le
  syndic (tracée). Politique par copropriété : `off` | `syndic` | `all` — les
  nouvelles copropriétés reçoivent `COPRO_TOTP_DEFAULT_POLICY` (défaut `syndic` ;
  l'app desktop la force à `off`). Le secret TOTP est chiffré en base (clé dérivée
  de `COPRO_SECRET_KEY` : **changer cette clé impose aux comptes de ré-enrôler leur
  2FA**). Les jetons intermédiaires (vérification du code, enrôlement forcé) sont à
  portée limitée et courts (10 / 30 min) ; les tentatives 2FA partagent le
  rate-limit du login.
- **Journal d'audit** : connexions (succès et échecs), activation / désactivation /
  réinitialisation 2FA, usage des codes de secours, création et suppression de
  comptes, exports (compte de gestion, quittances, rapport annuel, CSV, registre) et
  envois de relances — consultable par le syndic (page « 🔐 Sécurité ») pour la
  copropriété active.
- **Alertes email de sécurité** (best effort, via le SMTP de la copropriété) :
  connexion depuis une nouvelle IP, 2FA désactivée ou réinitialisée, code de
  secours utilisé.

## Recouvrement des impayés

Page « 💶 Recouvrement » (réservée au syndic) : par lot, un dossier suit la
procédure légale — relances email → **mise en demeure** → article 19-2 → amiable →
contentieux.

- **Décompte détaillé** : imputation FIFO des encaissements sur les appels les plus
  anciens ; distinction échu / à échoir. La mise en demeure liste la nature et le
  montant de chaque provision échue impayée (exigence de précision — cf. Cass. 3e
  civ., 18 juin 2026, n° 24-19.950).
- **Mise en demeure (PDF)** : générée depuis le dossier (mentions de la fiche
  Service-Public F2603 : identité et adresse du copropriétaire, décompte, délai de
  30 jours, conséquences). L'app trace le mode d'envoi et la référence (lettre
  recommandée électronique — la voie électronique est la règle, le papier
  l'exception — ou remise). L'envoi recommandé électronique se fait chez un
  prestataire externe (type AR24) : l'app prépare le courrier, le syndic l'envoie.
- **Article 19-2** : 30 jours après la mise en demeure restée infructueuse, l'app
  calcule les provisions non encore échues de l'exercice + les restes des exercices
  précédents devenus **immédiatement exigibles** (activation assistée, tracée,
  jamais automatique).
- **Intérêts et frais** : taux de l'intérêt légal paramétrable (arrêté semestriel,
  saisi par le syndic — pas de taux inventé par l'app), intérêts courus estimés
  depuis la mise en demeure, frais de recouvrement imputés au dossier (à la charge
  du débiteur).
- **Étapes suivantes** : conciliation / commissaire de justice / saisine du
  tribunal (≤ 5 000 € : règlement amiable obligatoire avant le juge, conciliateur
  gratuit ; le syndic n'a pas besoin d'autorisation d'AG pour le recouvrement ;
  prescription 5 ans).

⚠️ L'application **génère les courriers mais ne fournit pas de conseil
juridique** : faites valider les modèles par un conseil avant usage réel. Le syndic
ne peut pas avancer de fonds au syndicat (art. 18 de la loi du 10 juillet 1965) —
le module n'expose volontairement aucune fonction d'avance.

## Tests

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q            # 114 tests, ~70 % de couverture (pytest --cov)
```

La suite (pytest + TestClient, SQLite en mémoire) couvre : isolation multi-copro,
majorités légales (art. 24/25/26, unanimité, régime 2 copropriétaires, passerelle
25-1), tantièmes et appels de fonds (total ≠ 1000, arrondis au centime), soldes
par lot, authentification (register fermé, login, switch-copro, expiration),
double authentification (enrôlement, connexion en deux étapes, codes de secours à
usage unique, politiques par copropriété, réinitialisation par le syndic), journal
d'audit (droits, isolation inter-copro, pagination), fonds de travaux 5 %,
recouvrement (décompte FIFO et imputation, statuts du dossier, mise en demeure
générée, article 19-2, permissions syndic), thème utilisateur (défaut, mise à
jour, validation, NULL lisible), sessions (cookie HttpOnly, priorité d'auth,
migration, logout), génération PDF (non vide + régression
du compte de gestion) et un flux complet de bout en bout. CI : `.github/workflows/ci.yml` (push + PR).

L'ancien `test_e2e.py` (script urllib contre une instance réelle) vit désormais
dans `backend/scripts/smoke_e2e.py` : conservé comme smoke test manuel d'un
déploiement réel, le parcours équivalent tournant en CI dans `test_flux_complet.py`.

## Déploiement

Production : **https://proprietas.cloudfr.net** + legacy **https://copro.cloudfr.net**
(Cloudflare proxy → serveur de production, Caddy TLS Let's Encrypt).

### Profils de déploiement

- **Réseau local** (défaut) : `docker compose up -d` → l'application écoute sur le
  port 8000, accessible depuis votre réseau (aucun domaine requis).
- **Accès depuis internet** : `COPRO_DOMAIN="copro.exemple.fr" docker compose
  --profile internet up -d --build` → ajoute le proxy TLS (Caddy, certificats
  Let's Encrypt automatiques). Plusieurs domaines possibles, séparés par des
  virgules (`COPRO_DOMAIN="copro.fr, ancien.fr"`).

Dans l'application, le profil est affiché et VÉRIFIÉ : 🔐 Sécurité →
« Accès depuis internet » (réservé au syndic) — déclarez où vit l'application,
renseignez l'URL publique puis lancez le **diagnostic** (HTTPS, certificat, DNS,
en-têtes, rate-limit, couverture 2FA). La première requête vue depuis internet est
détectée automatiquement : un bandeau propose l'assistant — une exposition ne peut
pas passer inaperçue.

### Hébergement « maison » (sans ouvrir de ports)

Depuis une connexion personnelle, préférez un tunnel à l'ouverture de ports :
- **Cloudflare Tunnel** : `cloudflared tunnel --url http://localhost:8000` (essai) ;
  en production, un tunnel nommé vers votre domaine (Cloudflare Zero Trust, gratuit
  jusqu'à 50 utilisateurs) ;
- ou **Tailscale Funnel**.

Activez ensuite le durcissement dans 🔐 Sécurité → « Accès depuis internet » et
vérifiez avec le diagnostic.

### Migrations Alembic

Le schéma est géré par **Alembic** (`backend/alembic/`, URL lue depuis `COPRO_DATABASE_URL` —
aucune duplication dans `alembic.ini`). Les migrations tournent **explicitement**, jamais au
démarrage de l'application : le `CMD` du conteneur backend exécute `alembic upgrade head` puis
lance uvicorn (idempotent ; un seul conteneur backend dans le compose actuel).

- **Installation neuve** (nouveau serveur / base vide) : rien à faire, le conteneur migre seul.
- **Base existante créée par l'ancien `create_all` + `_MIGRATIONS`** (cas de l'instance
  actuelle) : bascule unique à faire **avant** de laisser démarrer le nouveau conteneur,
  pour marquer le schéma existant comme déjà migré sans le rejouer :

  ```bash
  cd /opt/copro-app
  git pull
  sudo docker compose build
  sudo docker compose run --rm backend sh -c "alembic stamp head"   # base existante : marquer, ne pas rejouer
  sudo docker compose up -d                                          # démarre : upgrade head = no-op + uvicorn
  ```

  Vérification : `sudo docker compose exec backend alembic current` doit afficher `head`.

- **Évolutions futures** : `alembic revision --autogenerate -m "..."` (backend/), relire la
  migration, commit, puis le déploiement l'applique au démarrage.

### Mise à jour

```bash
# Sur le serveur de production (utilisateur avec droits docker)
cd /opt/copro-app
git pull
sudo docker compose up -d --build                      # réseau local
sudo docker compose --profile internet up -d --build   # instance exposée (proxy TLS)
```

Le build multi-stage (Dockerfile racine `backend/Dockerfile`) compile le frontend (Node 20)
et construit le backend (Python 3.11) : plus aucune manipulation manuelle du bundle —
le conteneur sert le `dist/` produit au build. Le frontend est inclus dans l'image.

- `.env` (racine) : `POSTGRES_PASSWORD` + `COPRO_SECRET_KEY` (jamais commités)
- Attention : pas de `docker` sans sudo pour l'utilisateur du serveur → toujours `sudo docker compose …`
- Caddy redémarre automatiquement en cas d'échec de certificat (retry 60 s)
