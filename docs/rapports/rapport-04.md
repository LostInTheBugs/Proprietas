# Rapport tâche 04 — Migration vers Alembic

**Branche** : `chore/alembic` — 1 commit, PR #6 ouverte vers `main` (non mergée).
Rien n'a été appliqué sur l'instance de production.

## 1. Infrastructure Alembic — `backend/alembic/`

- `env.py` : URL lue depuis `app.core.config` (`COPRO_DATABASE_URL`) — **aucune duplication
  dans `alembic.ini`** (la ligne `sqlalchemy.url` y est commentée avec une note). Importe
  `app.models` pour que `Base.metadata` soit complet (autogenerate).
- `prepend_sys_path = .` (défaut d'`alembic init`), `script_location = %(here)s/alembic`.
- `render_as_batch=True` **uniquement** quand l'URL est SQLite (ALTER direct impossible ;
  en Postgres, batch = recréation de table inutile).
- `requirements.txt` : `alembic==1.19.1`.

## 2. Migration initiale — `ae4fc0457052`

Autogénérée sur une base SQLite vide, puis **relue soigneusement** :

- 22 tables, toutes les FKs, `ix_exercices_annee` et `ix_users_email` (unique) présents.
- Les blocs `batch_alter_table` produits par l'autogen (mode SQLite) ont été remplacés par
  des `create_index` / `drop_index` purs : SQLite supporte `CREATE INDEX` nativement, et
  Postgres évite une recréation de table inutile au premier déploiement.
- Types vérifiés : `Boolean` (SQLite INTEGER / PG boolean), `Float`, `Date`, `DateTime`,
  `Text` — cohérents avec `create_all`. Pas de `server_default` : les modèles utilisent des
  defaults Python, et l'ancien `create_all` n'en créait pas non plus → schéma équivalent.
- `nullable=True` partout sauf `nullable=False` explicite — identique au comportement de
  `create_all` (les defaults Python ne changent pas la nullabilité).

## 3. Bases existantes — choix : `alembic stamp head`

**Option retenue et documentée (README, section Déploiement → Migrations Alembic)** :
`stamp head` en étape unique avant le premier démarrage du nouveau conteneur.

Justification vs « migration initiale idempotente » :
- L'autogénération ne produit pas ce type de logique ; l'écrire à la main dupliquerait le
  schéma avec un risque d'écart silencieux ;
- Le `stamp` est une commande standard, vérifiable (`alembic current`) ;
- Le backfill `user_coproprietes` a déjà été exécuté en prod par l'ancien `migrate()` →
  marquer `head` ne rejoue rien (vérifié sur copie de la base dev : liaisons intactes).

Procédure exacte (dans le README) :
```bash
git pull && sudo docker compose build
sudo docker compose run --rm backend sh -c "alembic stamp head"
sudo docker compose up -d
```

## 4. `init_db()` remplacé

- `database.py` : `_MIGRATIONS`, `migrate()`, `init_db()` **supprimés** ; note en commentaire
  « ne jamais recréer de create_all au démarrage ».
- `main.py` : le lifespan ne migre plus. **Option retenue : étape explicite au démarrage du
  conteneur** (`CMD ["sh", "-c", "alembic upgrade head && uvicorn …"]` dans le Dockerfile),
  pas au lifespan — justification : un démarrage qui migre est dangereux avec plusieurs
  conteneurs (course), et l'explicite rend `alembic current` / les erreurs de migration
  visibles. C'est aussi ce qui colle au `docker-compose.yml` actuel (pas de service
  d'entrypoint dédié, un seul backend, `depends_on` db healthy).
- Dockerfile : `COPY alembic.ini` + `COPY alembic ./alembic` + CMD migré.

## 5. Vérification du chemin SQLite dev (de bout en bout)

1. Base vide → `alembic upgrade head` : 23 tables, `alembic_version = b1c9a3e2d4f5`,
   index présents.
2. Import de l'app : OK (98 routes).
3. `scripts/seed_demo.py` (via `PYTHONPATH=backend`, comme dans le conteneur) : 1 user,
   2 copros, 8 lots, 2 liaisons — OK.
4. **Démarrage réel** : uvicorn sur la base migrée → `/api/health` 200, login démo 200,
   `/api/lots` (5) et `/api/recap` (exercice 2026) OK. Le backend fonctionne sans `init_db`.
5. Base existante : copie de `backend/copro.db` → `alembic stamp head` → données intactes,
   `alembic current = head`, app OK.

## 6. Backfill `user_coproprietes` — `b1c9a3e2d4f5`

Migration de données dédiée (`INSERT … SELECT … WHERE NOT EXISTS`, idempotente) : sur base
neuve = no-op (tables vides) ; sur base stampée = no-op (déjà fait par l'ancien code) ;
utile uniquement pour une base intermédiaire. `downgrade` = no-op documenté (impossible de
distinguer les liaisons préexistantes).

## Points bloquants

Aucun. Rien appliqué en production.

## Requête d'inspection (si doute sur l'état réel du schéma prod, avant bascule)

```sql
-- via le conteneur db :
sudo docker compose exec db psql -U copro -c "\dt"
sudo docker compose exec db psql -U copro -c "\d users"          -- vérifier is_demo
sudo docker compose exec db psql -U copro -c "\d ags"            -- vérifier rappel_jours, convocation_envoyee
sudo docker compose exec db psql -U copro -c "SELECT COUNT(*) FROM user_coproprietes"
```

## Conflit de merge prévisible

La tâche 05 (docker multi-stage) réécrit `backend/Dockerfile` — la PR #6 modifie le même
fichier (COPY alembic + CMD). Conflit trivial à résoudre au merge (le nouveau Dockerfile
multi-stage devra conserver `COPY alembic` + `alembic upgrade head` dans le CMD) — signalé
dans les deux rapports.
