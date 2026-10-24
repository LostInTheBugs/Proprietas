# Rapport tâche 03 — Suite de tests pytest et CI GitHub Actions

**Branche** : `chore/tests-ci` — 1 commit, PR #5 ouverte vers `main` (non mergée).

## Infrastructure

- `backend/tests/conftest.py` : fixtures pytest — `client` (TestClient FastAPI branché sur
  SQLite en mémoire, `get_db` overridden), `db`, `db_engine` (base recréée à chaque test),
  `copro_a`, `copro_b`, `syndic_a`, `syndic_b`, `token_a`, `token_b`, helper `auth()`.
  ⚠️ Contenu **byte-identique** à celui de la branche T01 (PR #1) : quand les deux PR seront
  mergées, git fusionnera sans conflit (mêmes blobs). Les fixtures locales de
  `test_durcissement.py` (T02) shadowent proprement ce conftest une fois tout mergé.
- `backend/requirements-dev.txt` : `pytest`, `httpx`, `pytest-cov`, `pypdf` — séparé de
  `requirements.txt` (build Docker de prod intact).
- `.github/workflows/ci.yml` : déclencheurs `push` + `pull_request` ; job **backend**
  (Python 3.11, `pip install -r requirements.txt -r requirements-dev.txt`, `python -m pytest -q`
  — `python -m` requis pour que `tests.conftest` soit importable) et job **frontend**
  (Node 20, `npm ci`, `npm run build` incluant `tsc -b` donc le typecheck).
  Les deux jobs bloquent la PR en cas d'échec (checks GitHub).

## Couverture écrite (44 tests, 70 % — `TOTAL 2745 stmts`)

1. **Majorités** (`test_majorites.py`, 15 tests) : art. 24 (nominal 780/220 adoptée ;
   égalité 500/500 rejetée ; abstentions exclues ; aucun exprimé rejeté), art. 25 (nominal ;
   limite 500/500), art. 26 (nominal 780 ≥ 2/3 ; limite 660 < 666,67), unanimité (nominal ;
   une abstention → rejet), régime 2 copropriétaires art. 41-16 (art. 24 > 50 % ; art. 25
   ≥ 2/3, deux cas), passerelle art. 25-1 (rejet art. 25 → adoption art. 24 mêmes voix).
2. **Tantièmes** (`test_tantiemes.py`, 11 tests) : répartition total 1000 (± fonds travaux),
   total ≠ 1000 (b3f542b) via unité ET via API, arrondis (reste imputé au premier lot,
   somme == montant au centime sur 5 montants, fonds travaux 1,05 ×), sans lots → vide.
3. **Soldes par lot** (`test_soldes.py`, 3 tests) : nominal (840 payé / 500 partiel),
   solde négatif (crédit -160), vide (0/0/0).
4. **Auth** (`test_auth.py`, 9 tests) : register premier compte, fermé après compte
   non-démo, reste ouvert avec compte démo, login OK/mauvais mdp/casse, switch-copro
   (200 vers liée, 403 vers non liée), token expiré (401), token falsifié (401).
5. **Fonds de travaux** (`test_fonds_travaux.py`, 3 tests) : taux minimum légal 5 %,
   appel avec FT (50 € sur 1000), sans FT (0).
6. **PDF** (`test_pdf.py`, 5 tests) : 4 générateurs produisent un PDF non vide
   (`%PDF-`, > 1 Ko) — rapport annuel, compte de gestion, PV, quittances ; régression
   **2338e58** couverte : `story_compte_gestion` alimente bien le story passé
   (l'ancien bug le réinitialisait → section perdue), et la section « COMPTE DE GESTION
   DE L'EXERCICE » + budget sont présents dans le rapport annuel (extraction pypdf).
   Note : `register_fonts()` doit être appelé avant `story_compte_gestion` hors générateur
   (les générateurs l'appellent eux-mêmes).
7. **Flux complet** (`test_flux_complet.py`) : conversion de l'ancien `test_e2e.py`
   (register → copro → personnes → lots 1000‰ → exercice → budget → appel 3000 € FT 5 %
   → mouvements → récap 1382/350/solde 319 → AG art25/art26 → export registre → documents
   → contacts/contrats).

## Nettoyage de test_e2e.py — choix documenté

`backend/test_e2e.py` (script urllib non collectable) → **déplacé** vers
`backend/scripts/smoke_e2e.py` : il garde une utilité réelle comme smoke test manuel contre
une instance déployée (uvicorn + base réelle + SMTP), documenté dans son en-tête. Le
parcours équivalent tourne en CI dans `test_flux_complet.py`. Choix expliqué dans le README
(section Tests).

## Bug découvert au passage

`create_appel` plantait en `KeyError: montant_fonds_travaux` pour tout appel sans fonds
travaux (taux = 0) — corrigé dans `comptes.py` (même correctif que la PR #1 ; contenu
identique → merge sans conflit).

## Vérification

- `python -m pytest tests/ -q` → **44 passed** (6 s).
- `pytest --cov=app` → **70 %** global (points forts : schemas 100 %, country_rules 98 %,
  copro 98 %, compte_gestion 99 %, pv_pdf 93 %, rapport_annuel 91 %).
- CI : workflow YAML validé (pas de lint YAML dédié, syntaxe GitHub Actions standard).

## Points bloquants

Aucun.

## Hors périmètre

- `relance_auto.py` / `rappels_ag.py` (cron) : 0 % de couverture — nécessitent un moteur de
  temps injectable ; non exigé par la tâche, signalé pour une suite.
- Couverture emailer 22 % : envoi SMTP réel non testable en CI sans mock (le mock SMTP
  `aiosmtpd` pourrait être ajouté plus tard).
