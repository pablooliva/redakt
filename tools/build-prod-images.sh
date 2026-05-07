#!/usr/bin/env bash
# Build the three prod images for linux/amd64 and load them into the
# local Docker daemon. Does NOT transfer anything anywhere — that's
# what tools/deploy-prod-images.sh is for.
#
# Single-arch linux/amd64 to match the Hetzner production host (x86_64).
# On Apple Silicon hosts buildx runs amd64 under QEMU emulation, which
# makes the analyzer image's transformer install slow on first build
# (~30-60 min). Subsequent builds reuse layer cache and are much faster.
#
# Usage:
#   ./tools/build-prod-images.sh

set -euo pipefail

PLATFORM="linux/amd64"

cd "$(git rev-parse --show-toplevel)"

build() {
    local tag="$1"
    local context="$2"
    local dockerfile="$3"
    shift 3

    echo
    echo "==> Building $tag for $PLATFORM"
    docker buildx build \
        --platform "$PLATFORM" \
        --load \
        --tag "$tag" \
        -f "$dockerfile" \
        "$@" \
        "$context"
}

build redakt-redakt:latest . Dockerfile

build redakt-presidio-analyzer:latest \
    presidio/presidio-analyzer \
    presidio/presidio-analyzer/Dockerfile.multi \
    --build-arg NLP_CONF_FILE=presidio_analyzer/conf/multi.yaml

build redakt-presidio-anonymizer:latest \
    presidio/presidio-anonymizer \
    presidio/presidio-anonymizer/Dockerfile

echo
echo "==> Built (linux/amd64):"
docker images --filter 'reference=redakt-*' --format 'table {{.Repository}}\t{{.Tag}}\t{{.Size}}'
echo
echo "Next: ./tools/deploy-prod-images.sh to stream to the Hetzner box."
