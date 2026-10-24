# Rapport tâche 02 — Durcissement configuration & authentification

**Branche** : `fix/durcissement-config-auth` — 4 commits, PR #2 ouverte vers `main` (non mergée).
**Issues GitHub** : #3 (chiffrement SMTP) et #4 (migration deps) — ouvertes.

## 1. Clé JWT par défaut — `app/core/config.py`

`get_settings()` refuse désormais le démarrage si `secret_key == "change-me"` **et**
`database_url` n'est pas SQLite : `RuntimeError` nommant `COPRO_SECRET_KEY` explicitement.
Toléré en dev SQLite (le .env de dev a déjà `dev-secret-test`). Documenté dans le README
(section Sécurité) et `.env.example` (valeur vide + commande de génération).

## 2. Fallback dangereux — `app/routes/copro.py`

Un compte **sans liaison** `UserCopro` ne récupère plus la première copropriété de la base :
il crée une copropriété neuve (« Ma copropriété ») et s'y lie. Le comportement « premier
login » (base vide → création) est conservé — seul le cas « base non vide + compte sans
lien » change, et c'est exactement la faille.

## 3. Routes utilisateurs scopées — `app/routes/auth.py`

`list_users` et `delete_user` sont restreints à la copropriété active (JOIN
`user_coproprietes`). Le garde-fou « impossible de supprimer son propre compte » (400)
est conservé ; un compte d'une autre copro → 404 (idem id inexistant). `get_or_create_copro`
importé en tête de fichier (plus d'import local).

## 4. CORS — `app/main.py`

`allow_origins` configurable via `COPRO_CORS_ORIGINS` (JSON, défaut `[]`). En dev SQLite
sans configuration, `["http://localhost:5173"]` est appliqué automatiquement. En prod,
le frontend étant servi par le même backend, le CORS permissif disparaît.

## 5. Secrets SMTP — schémas + frontend

- `smtp_password` **retiré de `CoproOut`** (et du type `Copro` frontend) : le secret ne
  sort plus jamais de l'API.
- `Settings.tsx` : le champ devient « Nouveau mot de passe » (placeholder « laisser vide
  pour conserver ») ; envoyé uniquement s'il est non vide (save ET test). Le backend
  (`SmtpConfigIn`) accepte toujours les mises à jour.
- Chiffrement applicatif : **issue #3** (clé dérivée de `COPRO_SECRET_KEY` via HKDF,
  `cryptography.fernet`, déchiffrement au point d'usage dans `emailer.py`, migration
  des valeurs existantes).

## 6. Upload documents — `app/routes/documents.py`

- Plafond : `upload_max_mb` (défaut 25) → **413** « Fichier trop volumineux ».
- Liste blanche d'extensions `.pdf .jpg .jpeg .png .doc .docx .xls .xlsx .odt .ods`
  → **400** « Type de fichier refusé ». Extension normalisée en minuscules.

## 7. Rate limiting — `app/core/rate_limit.py` (nouveau)

Limiteur en mémoire : 5 échecs par (email, IP) sur 15 min → **429** sur
`/api/auth/login`. Les échecs sont enregistrés, effacés après succès. Documenté dans le
README. Limite connue : IP = `request.client.host` (derrière un reverse proxy, toutes
les requêtes semblent venir du proxy — acceptable mono-serveur, à affiner avec
X-Forwarded-For si nécessaire).

## 8. Dépendances — issue #4

Migration `python-jose → pyjwt` et `passlib → bcrypt` direct **non exécutée** dans cette
PR (comme demandé). Issue #4 détaillant le diff (`app/core/security.py` seul) et le
risque hash : **vérifié expérimentalement** — les hash passlib (`$2b$12$…`) sont lisibles
par `bcrypt.checkpw` seul, aucun re-hash nécessaire ; réciproque vérifiée aussi.

## Tests — `backend/tests/test_durcissement.py` (10 tests, pytest)

- Points 1, 2, 3 comme exigé + bonus 6 et 7 :
  - garde `secret_key` hors SQLite (raise) / toléré en SQLite ;
  - compte sans lien → nouvelle copro (≠ copro de A) + premier login base vide ;
  - `list_users` scopé (pas de fuite du compte de B), `delete_user` scopé (404 inter-copro,
    400 auto-suppression, 200 intra-copro) ;
  - upload : extension `.exe` → 400, taille > plafond → 413 ;
  - login : 5 échecs puis 429 (même avec bon mdp), reset après succès.
- Résultat : **10 passed**.
- Note : fichier **autonome** (fixtures locales) pour ne pas dépendre de la branche T01
  non mergée ; une fois la PR #1 mergée, ces fixtures shadowent le conftest sans conflit
  (vérifié : la résolution pytest donne priorité aux fixtures du module de test).

## Build

- Backend : import complet OK (98 routes), `py_compile` OK sur les 7 fichiers modifiés.
- Frontend : `npm run build` OK (tsc -b inclus, typecheck).

## Points bloquants

Aucun.

## Hors périmètre

- Chiffrement SMTP et migration deps : issues #3 / #4 (volontairement hors PR).
- `bcrypt` reste épinglé à 4.0.1 dans cette PR (dépinglé dans la future migration #4).
