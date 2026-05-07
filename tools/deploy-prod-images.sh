#!/usr/bin/env bash
# Stream locally-built prod images to the Hetzner host via SSH. No
# registry involved — `docker save` on the developer side, piped over
# SSH, `docker load` on the server.
#
# Trade-off vs a registry: every deploy transfers the FULL image (no
# layer reuse on the wire), so this is fine for infrequent deploys but
# painful if you push multiple times per day.
#
# Prerequisites:
#   - ./tools/build-prod-images.sh has been run (images exist locally,
#     tagged redakt-*:latest, built for linux/amd64).
#   - SSH access to the host (default alias: Hetzner-personal; override
#     via REDAKT_PROD_HOST=...).
#
# Usage:
#   ./tools/deploy-prod-images.sh
#   REDAKT_PROD_HOST=user@1.2.3.4 ./tools/deploy-prod-images.sh

set -euo pipefail

SERVER="${REDAKT_PROD_HOST:-Hetzner-personal}"
IMAGES=(
    "redakt-redakt:latest"
    "redakt-presidio-analyzer:latest"
    "redakt-presidio-anonymizer:latest"
)

# Sanity-check: each image exists locally and is amd64.
for img in "${IMAGES[@]}"; do
    if ! docker image inspect "$img" >/dev/null 2>&1; then
        echo "ERROR: $img not found locally." >&2
        echo "Run ./tools/build-prod-images.sh first." >&2
        exit 1
    fi
    arch=$(docker image inspect "$img" --format '{{.Architecture}}')
    if [[ "$arch" != "amd64" ]]; then
        echo "ERROR: $img is $arch, but the prod target is amd64." >&2
        echo "Rebuild with ./tools/build-prod-images.sh (it forces linux/amd64)." >&2
        exit 1
    fi
done

# Sanity-check: SSH reachable.
if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$SERVER" true 2>/dev/null; then
    echo "ERROR: cannot reach $SERVER via SSH." >&2
    echo "Check your ~/.ssh/config or set REDAKT_PROD_HOST=user@host." >&2
    exit 1
fi

echo "==> Streaming ${#IMAGES[@]} images to $SERVER"
for img in "${IMAGES[@]}"; do echo "    $img"; done
echo "    (gzip-compressed; ~10 GB on the wire — expect minutes, not seconds)"
echo

docker save "${IMAGES[@]}" \
    | gzip \
    | ssh "$SERVER" "gunzip | docker load"

echo
echo "==> Loaded on $SERVER. Next steps on the server:"
echo "    cd ~/redakt   # (or wherever docker-compose.prod.yml lives)"
echo "    docker compose -f docker-compose.prod.yml up -d"
echo "    docker compose -f docker-compose.prod.yml ps"
