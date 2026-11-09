#!/usr/bin/env bash
# Ne garde sur GitHub que la dernière release et la dernière image GHCR.
#   scripts/nettoyer-github.sh <tag>            supprime
#   DRY_RUN=1 scripts/nettoyer-github.sh <tag>  affiche seulement ce qui serait supprimé
# Les tags git sont TOUJOURS conservés (historique, stratégie « build » des serveurs).
# Seules les releases et les images ANTÉRIEURES à <tag> sont supprimées ; une version plus
# récente (publiée entre-temps) n'est jamais touchée. Les serveurs gardent l'image qu'ils ont
# déjà téléchargée. Appelé par .github/workflows/release.yml (job « nettoyage »), après la
# publication de l'image de <tag>.
# Besoins : gh (GH_TOKEN avec contents:write + packages:write, GH_REPO=propriétaire/dépôt), jq,
# docker buildx (lecture de l'index de l'image).
set -euo pipefail
TAG="${1:?usage : nettoyer-github.sh <tag>}"
REPO="${GH_REPO:?GH_REPO manquant (ex. LostInTheBugs/Proprietas)}"
OWNER="${REPO%%/*}"
PAQUET="${PAQUET:-proprietas}"
IMAGE="ghcr.io/$(echo "$OWNER" | tr 'A-Z' 'a-z')/$PAQUET"
DRY="${DRY_RUN:-0}"

anterieur() {  # vrai si la version $1 est strictement antérieure à $TAG
  [ "$1" != "$TAG" ] && [ "$(printf '%s\n%s\n' "$1" "$TAG" | sort -V | tail -1)" = "$TAG" ]
}

action() {  # $1 = description, puis la commande
  local quoi="$1"; shift
  if [ "$DRY" = "1" ]; then echo "[simulation] $quoi"; else "$@" >/dev/null; echo "$quoi"; fi
}

# ---------- Releases (le tag git reste : pas de --cleanup-tag)
gh release view "$TAG" --repo "$REPO" >/dev/null   # la release du tag doit exister
n=0
while read -r t; do
  [ -n "$t" ] || continue
  if anterieur "$t"; then
    action "release $t supprimée" gh release delete "$t" --repo "$REPO" --yes
    n=$((n + 1))
  fi
done < <(gh api --paginate "repos/$REPO/releases?per_page=100" --jq '.[].tag_name')
echo "releases : $n supprimée(s), $TAG gardée"

# ---------- Images GHCR
if [ "$(gh api "users/$OWNER" --jq .type)" = "Organization" ]; then BASE="orgs/$OWNER"; else BASE="users/$OWNER"; fi
URL="$BASE/packages/container/$PAQUET/versions"
VERSIONS=$(gh api --paginate "$URL?per_page=100" \
  --jq '.[] | [.id, .name, .created_at, ((.metadata.container.tags // []) | join(","))] | @tsv')
GARDE=$(printf '%s\n' "$VERSIONS" | awk -F'\t' -v t="$TAG" '{n=split($4,a,","); for(i=1;i<=n;i++) if(a[i]==t) print}')
[ "$(printf '%s\n' "$GARDE" | grep -c .)" = "1" ] || { echo "image $TAG introuvable sur GHCR : rien n'est supprimé" >&2; exit 1; }
GARDE_DIGEST=$(printf '%s' "$GARDE" | cut -f2)
GARDE_DATE=$(printf '%s' "$GARDE" | cut -f3)
# Manifestes référencés par l'image gardée (index : image par plateforme, attestation) : à garder.
ENFANTS=$(docker buildx imagetools inspect --raw "$IMAGE:$TAG" | jq -r '.manifests[]?.digest')
n=0
while IFS=$'\t' read -r id digest cree tags; do
  [ -n "$id" ] || continue
  [ "$digest" = "$GARDE_DIGEST" ] && continue
  printf '%s\n' "$ENFANTS" | grep -qxF "$digest" && continue
  [[ "$cree" < "$GARDE_DATE" ]] || continue          # plus récente que l'image gardée : on n'y touche pas
  action "image ${tags:-sans tag} ($digest) supprimée" gh api -X DELETE "$URL/$id"
  n=$((n + 1))
done <<< "$VERSIONS"
echo "images : $n supprimée(s), $TAG gardée"
