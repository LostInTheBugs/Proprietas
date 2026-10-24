# Rapport tâche 05 — Build Docker multi-stage (frontend dans l'image)

**Branche** : `chore/docker-multistage` — 3 commits, PR #7 ouverte vers `main` (non mergée).
Rien n'a été appliqué sur l'instance de production.

## 1. Dockerfile multi-stage — `backend/Dockerfile`

- **Stage 1 `node:20-alpine`** : `COPY frontend/package.json frontend/package-lock.json` puis
  `npm ci` (couche cache : pas de re-téléchargement tant que les deps ne changent pas), puis
  `COPY frontend/ ./` et `npm run build` (inclut `tsc -b` → le typecheck échoue le build).
- **Stage 2 `python:3.11-slim`** : requirements (pip), app, alembic (scaffold copié de la
  PR #6, byte-identique → auto-merge), puis `COPY --from=frontend-build /src/frontend/dist
  ./frontend_dist` ; `CMD ["sh","-c","alembic upgrade head && uvicorn …"]`.
- Build context : **racine du dépôt** (`docker-compose.yml` → `build: { context: ., dockerfile: backend/Dockerfile }`).

## 2. `.dockerignore` (nouveau, racine)

`node_modules`, `frontend/dist`, `**/__pycache__`, `*.pyc`, `*.db`, `.venv`, `.env`,
`uploads`, `claude/`, `.git`, `*.tsbuildinfo`, `rapport-*.md` — contexte de build minimal
(2,54 Mo transférés au build).

## 3. `docker-compose.yml`

- Volume `./frontend_dist:/app/frontend_dist:ro` **supprimé** (le bundle est dans l'image).
- **Healthcheck backend ajouté** : `python -c "urllib.request.urlopen('http://127.0.0.1:8000/api/health')"`,
  interval 30 s, start_period 20 s (le `db` en avait déjà un).
- `restart`, env, volumes uploads : inchangés.

## 4. Stratégie de cache frontend — non régressée (vérifiée)

`app/main.py` inchangé : `/assets/*` (hashés Vite) → `public, max-age=31536000, immutable` ;
`/` (index.html) → `no-cache, no-store, must-revalidate`. Le bundle copié depuis le stage 1
est servi exactement comme avant.

## 5. Vérifications effectuées (VM locale — docker 29.1.3 installé pour l'occasion)

1. `sudo docker compose build` → OK (le premier essai a échoué : `backend/alembic.ini`
   absent de `main` car la PR #6 n'est pas mergée → la branche embarque le scaffold
   byte-identique, cf. §7).
2. **Taille finale de l'image : 401 Mo** (`copro-app-backend:latest`) — détail :
   python:3.11-slim (~200 Mo) + couche pip 161 Mo (reportlab, psycopg2-binary,
   cryptography…) + code 2,4 Mo + bundle frontend 332 Ko. **Le stage Node ne fuit pas** :
   `ls /app` = {alembic, alembic.ini, app, frontend_dist, requirements.txt, uploads},
   `node_modules` et `/src` absents (vérifié `docker run --entrypoint sh`).
3. **Test complet avec Postgres jetable** (projet `copro-t05`, ports non conflictuels,
   caddy exclu via profile, `down -v` après) :
   - `db` → healthy, puis `backend` → **healthy** (healthcheck OK) ;
   - `alembic upgrade head` exécuté au démarrage du conteneur (schéma complet créé sur
     Postgres vide — preuve que la migration explicite fonctionne dans le flux CMD) ;
   - API : `POST /api/auth/register` → token → `GET /api/copro` (auto-création
     « Ma copropriété ») → `POST /api/lots` → tout 200 ;
   - Frontend : `GET /` 200 (index.html, `no-store`), `GET /assets/index-*.js` 200
     (`immutable`, max-age 1 an).
4. Stack jetable démontée (conteneurs + volumes), image finale conservée.

## 6. README — mise à jour

Section Déploiement : « Mise à jour » = `git pull && sudo docker compose up -d --build`
(un-liner), plus de tar/ssh manuel du bundle ; procédure Alembic (stamp prod) conservée ;
note « Attention : pas de docker sans sudo ». Les lignes tar/ssh de l'ancien flux ont été
retirées.

## 7. Décisions

- **Branche autonome** : `backend/alembic/`, `alembic.ini`, `alembic==1.19.1` copiés
  **byte-identiques** depuis `chore/alembic` (PR #6) — sans cela le Dockerfile (qui
  référence alembic) ne construit pas sur `main`. Blobs identiques → quand les deux PRs
  seront mergées, git fusionne sans conflit (comme `conftest.py` en tâche 03).
- **Conflit de merge attendu** : `backend/Dockerfile` (modifié par PR #6 et #7) et
  `README.md` (section Déploiement réécrite par les deux). Résolution triviale : garder le
  Dockerfile multi-stage (il contient déjà les lignes alembic) et la procédure Alembic.
- **Docker installé sur la VM** (`docker.io` 29.1.3 + compose v2, sudo requis — l'utilisateur
  `administrator` a été ajouté au groupe `docker` mais il faudra une nouvelle session pour
  s'en servir sans sudo).

## Hors périmètre / pistes

- 401 Mo reste optimisable (base alpine + wheels musl, `--no-install-recommends`) — non
  exigé, le stage Node ne fuit pas.
- Le test n'a pas touché à la production ni au `frontend_dist/` local de la VM.
