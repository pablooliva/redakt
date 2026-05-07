#!/usr/bin/env bash
# Build the three prod images and push them to GHCR.
#
# Single-arch linux/amd64 to match the Hetzner production host (x86_64).
# On Apple Silicon hosts buildx runs amd64 under QEMU emulation, which
# makes the analyzer image's transformer install slow on first build
# (~30-60 min). Subsequent builds reuse layer cache and are much faster.
#
# Tagging strategy: every image is pushed with both :latest (rolling)
# and :<git-short-sha> (pinable). docker-compose.prod.yml defaults to
# REDAKT_IMAGE_TAG=latest; deploys can pin via the env var.
#
# Prerequisites:
#   - docker login ghcr.io   (PAT with read:packages + write:packages)
#   - clean working tree     (the SHA tag would otherwise be misleading)
#
# Usage:
#   ./tools/build-and-push-prod.sh

set -euo pipefail

REGISTRY="ghcr.io/pablooliva"
PLATFORM="linux/amd64"

cd "$(git rev-parse --show-toplevel)"

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "ERROR: working tree has uncommitted changes." >&2
    echo "Commit or stash before pushing — the SHA tag must reflect what's pushed." >&2
    exit 1
fi

GIT_SHA="$(git rev-parse --short HEAD)"

build_and_push() {
    local image_name="$1"
    local context="$2"
    local dockerfile="$3"
    shift 3

    local full="$REGISTRY/$image_name"
    echo
    echo "==> Building + pushing $full"
    echo "    sha: $GIT_SHA  platform: $PLATFORM"
    docker buildx build \
        --platform "$PLATFORM" \
        --tag "$full:$GIT_SHA" \
        --tag "$full:latest" \
        --push \
        -f "$dockerfile" \
        "$@" \
        "$context"
}

build_and_push redakt . Dockerfile

build_and_push redakt-presidio-analyzer \
    presidio/presidio-analyzer \
    presidio/presidio-analyzer/Dockerfile.multi \
    --build-arg NLP_CONF_FILE=presidio_analyzer/conf/multi.yaml

build_and_push redakt-presidio-anonymizer \
    presidio/presidio-anonymizer \
    presidio/presidio-anonymizer/Dockerfile

echo
echo "==> Done. Pushed at sha=$GIT_SHA:"
echo "    $REGISTRY/redakt:{$GIT_SHA,latest}"
echo "    $REGISTRY/redakt-presidio-analyzer:{$GIT_SHA,latest}"
echo "    $REGISTRY/redakt-presidio-anonymizer:{$GIT_SHA,latest}"
