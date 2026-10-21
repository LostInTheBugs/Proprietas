# Changelog

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
