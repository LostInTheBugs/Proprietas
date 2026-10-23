#!/usr/bin/env bash
# Passe le dépôt à une nouvelle version (format AAAA.MM.NNN ou AAAA.MM.NNN-cX).
#   scripts/bump-version.sh 2026.10.002
# Met à jour VERSION, backend/app/core/version.py, README, frontend/package.json,
# frontend/package-lock.json et frontend/index.html. Vérifie qu'une entrée existe
# dans CHANGELOG.md (le workflow de release en tire les notes).
set -euo pipefail
cd "$(dirname "$0")/.."
NEW="${1:?usage : scripts/bump-version.sh AAAA.MM.NNN}"
[[ "$NEW" =~ ^[0-9]{4}\.[0-9]{2}\.[0-9]{3}(-c[0-9]+)?$ ]] || { echo "format invalide : $NEW" >&2; exit 1; }
OLD="$(cat VERSION)"
grep -q "^## $NEW " CHANGELOG.md || { echo "ajoutez d'abord « ## $NEW — date » dans CHANGELOG.md" >&2; exit 1; }
O="${OLD//./\\.}"
sed -i "s/$O/$NEW/" README.md backend/app/core/version.py frontend/index.html frontend/package.json
sed -i "0,/\"version\": \"$O\"/s//\"version\": \"$NEW\"/; 0,/\"version\": \"$O\"/s//\"version\": \"$NEW\"/" frontend/package-lock.json
echo "$NEW" > VERSION
if grep -rn "$O" README.md backend/app/core/version.py frontend/index.html frontend/package.json frontend/package-lock.json; then
  echo "des occurrences de $OLD subsistent (ci-dessus)" >&2; exit 1
fi
echo "$OLD → $NEW : commit, puis  git tag $NEW && git push origin $NEW"
