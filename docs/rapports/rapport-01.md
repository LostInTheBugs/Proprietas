# Rapport tâche 01 — Isolation multi-copropriétés (IDOR)

**Branche** : `fix/isolation-multicopro` — 9 commits, PR ouverte vers `main` (non mergée).

## Occurrences corrigées (34, dont 2 hors grep)

Toutes les routes d'accès par identifiant vérifient désormais que l'objet appartient
à la copropriété active (404 systématique, jamais 403 — on ne divulgue pas l'existence
d'un objet d'une autre copropriété).

| Fichier | Occurrences | Type de scoping |
|---|---|---|
| `app/routes/ag.py` | 17 | AG direct ×10 ; Resolution via AG ×4 ; AgCreneau via AG ×2 ; + lot scoping dans les votes ×2 (hors grep) |
| `app/routes/lots.py` | 4 | Personne ×2, Lot ×2 (direct) |
| `app/routes/comptes.py` | 4 | Exercice (helper `get_exercice`, 8 routes couvertes), BudgetLine via Exercice, AppelFonds via Exercice, Mouvement direct |
| `app/routes/carnet.py` | 2 | Entretien direct |
| `app/routes/contacts.py` | 2 | Contact direct |
| `app/routes/contrats.py` | 2 | Contrat direct |
| `app/routes/documents.py` | 2 | Document direct + durcissement download |
| `app/routes/travaux.py` | 2 | Travaux direct |

Vérification : `grep -rn "\.id == [a-z_]*_id" app/routes/ | grep -v copropriete_id | grep -v auth.py`
ne retourne plus que le pattern volontairement conservé de `ag.py` (`choisir_creneau`, ligne 235,
déjà scopé par jointure sur `ag`).

## Helper centralisé — `app/core/scoping.py`

- `get_owned(db, model, obj_id, copro, label, message)` : objets avec `copropriete_id`.
- `get_owned_via(db, model, parent_model, obj_id, copro, parent_fk, label, message)` :
  objets enfants scopés par **jointure** sur leur parent (paramètre `parent_fk` explicite,
  pas de magie). Messages d'erreur français existants conservés à l'identique
  (y compris « Travaux introuvables » via `message`).

## Modèles sans `copropriete_id` direct (scoping par jointure)

- `Resolution` → parent `AG` (`ag_id`)
- `AgCreneau` → parent `AG` (`ag_id`)
- `BudgetLine` → parent `Exercice` (`exercice_id`)
- `AppelFonds` → parent `Exercice` (`exercice_id`)
- (`AppelLot`, `Vote`, `AgCreneauVote` : jamais accédés par id directement — uniquement
  créés/listés via des parents déjà scopés ; vérifié dans les routes)

## Chaînes vérifiées au-delà de l'objet feuille

- `set_vote` / `set_creneau_vote` : le `lot_id` passé dans le corps est aussi scopé
  (un syndic ne peut plus voter avec un lot d'une autre copro).
- `choisir_creneau` : `ag` scopé, le pattern `AgCreneau.id == creneau_id, AgCreneau.ag_id == ag.id`
  conservé tel quel (déjà correct).
- `_resolution_out` / `calculer` / `_creneau_out` : les chargements `db.query(Lot).all()`
  étaient **non scopés** (fuite de données inter-copro dans les calculs de majorité et de
  tantièmes) → filtrés par copropriété.

## Cas particulier `documents.py`

- Scoping complet de `download_document` (y compris l'accès par `?token=`) et `delete_document`.
- **Injection Content-Disposition** : nouveau `_safe_download_name()` — retire caractères de
  contrôle (CR/LF) et guillemets du libellé avant passage à `FileResponse(filename=...)`.
- **Traversal** : nouveau `_fichier_path()` — `abspath` + `startswith(upload_dir + os.sep)`,
  sinon 404. Appliqué au download ET au delete.

## Bug préexistant découvert et corrigé (comptes.py)

`create_appel` plantait en `KeyError: montant_fonds_travaux` dès qu'un appel de fonds était
créé **sans** fonds travaux inclus (taux = 0 → la clé absente des parts). Corrigé avec
`p.get("montant_fonds_travaux", 0.0)` aux deux endroits. Le chemin « avec fonds travaux »
(couvert par `test_e2e.py`) ne change pas.

## Tests — `backend/tests/` (13 tests, pytest + TestClient, SQLite en mémoire)

- `conftest.py` : fixtures `client`, `db`, `db_engine`, `copro_a`, `copro_b`, `syndic_a/b`,
  `token_a/b`. Env `COPRO_DATABASE_URL=sqlite://` posé avant import ; pas de lifespan
  (pas de `init_db`, pas de scheduler).
- `test_isolation.py` : pour chaque type (personne, lot, document, AG, résolution, créneau,
  mouvement, contact, contrat, entretien, travaux, exercice, budget, appel) :
  token B → **404** sur GET/PUT/DELETE par id + POST chaînés ; token A → accès normal.
- Couverture demandée par la tâche : personne, lot, document, AG, résolution, mouvement,
  contact, contrat, entretien, travaux ✔ (plus exercice/budget/appel/créneaux/votes).
- Cas documents : injection en-tête (CR/LF retirés) et confinement `../../etc/passwd` → 404.

Résultat : **13 passed**.

## Points bloquants

Aucun.

## Hors périmètre (signalé)

- `.gitignore` : ajout de `claude/` (dossier de prompts de travail, exigence explicite :
  ne jamais le pousser sur GitHub).
- `auth.py` (list_users/delete_user non scopés) : traité en tâche 02.
- `relances.py`, `export.py`, `consolide.py` : vérifiés, déjà scopés via copro.
