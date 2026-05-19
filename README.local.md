# Production Deployment

Production is deployed manually. Use the current state of the `pablo` branch and copy files over to the server directly. The GitHub repo is not used as the conduit to push to production.

## Deploying Docker Images

Two scripts under `tools/` cover the image build + ship workflow. No registry is involved — images are built locally and streamed to the Hetzner host over SSH.

```bash
./tools/build-prod-images.sh       # local linux/amd64 build, ~30-60 min first run
./tools/deploy-prod-images.sh      # save | ssh | load to Hetzner-personal, ~5-15 min
```

### 1. Build (`tools/build-prod-images.sh`)

Builds three images for `linux/amd64` (to match the Hetzner x86_64 host) and loads them into the local Docker daemon:

- `redakt-redakt:latest` — the Redakt API + frontend
- `redakt-presidio-analyzer:latest` — Presidio Analyzer (multi-language NLP config)
- `redakt-presidio-anonymizer:latest` — Presidio Anonymizer

On Apple Silicon, buildx runs amd64 under QEMU emulation. First build is slow (~30–60 min, mostly the analyzer's transformer install); subsequent builds reuse layer cache.

### 2. Deploy (`tools/deploy-prod-images.sh`)

Pipes `docker save | gzip | ssh <host> "gunzip | docker load"` for each image. No layer reuse on the wire — every deploy transfers the full ~10 GB, so this is fine for infrequent deploys but painful for multiple pushes per day.

Defaults to the SSH alias `Hetzner-personal`. Override with:

```bash
REDAKT_PROD_HOST=user@1.2.3.4 ./tools/deploy-prod-images.sh
```

The script sanity-checks that each image exists locally, is `amd64`, and that SSH is reachable before transferring.

### 3. Restart on the server

After `deploy-prod-images.sh` finishes, SSH to the host and bounce the stack:

```bash
ssh Hetzner-personal
cd /opt/docker/redakt   # where docker-compose.prod.yml lives on the Hetzner box
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
```

`docker-compose.prod.yml` must already exist on the server and reference the `redakt-*:latest` tags loaded in step 2.

## Audit logs

Audit lines (one JSON entry per `/api/detect` and `/api/anonymize` request) are persisted on the prod host at:

```
/var/log/redakt/audit.log
```

The path is bind-mounted into the redakt container at the same location (see `docker-compose.prod.yml`'s `volumes:` entry on the redakt service). Rotation is handled by Python's `RotatingFileHandler`: **10 MB max per file × 5 backups** (configured in `config.yaml` under `audit_log_max_bytes` / `audit_log_backup_count`). When the active file hits 10 MB it rolls to `audit.log.1`, then `.2`, etc., and the oldest is discarded.

One-time host setup (already applied to the current Hetzner box):

```bash
ssh Hetzner-personal '
  mkdir -p /var/log/redakt && \
  chown 1001:1001 /var/log/redakt
'
```

UID 1001 matches the `redakt` user inside the container (`Dockerfile:18`). Without correct ownership the file handler fails to create, `audit.py` logs a one-line warning, and the container falls back to stdout-only logging.

Useful reads:

```bash
# tail live audit JSON from the host
ssh Hetzner-personal 'tail -f /var/log/redakt/audit.log'

# rotated history
ssh Hetzner-personal 'ls -la /var/log/redakt/'

# audit + uvicorn access logs from the running container (stdout sink is still active)
ssh Hetzner-personal 'docker logs redakt-redakt-1 --tail 50 --follow'
```

The audit logger writes **metadata only** — timestamp, action, entity-type counts, language, source, closed-world telemetry. Original text and detected PII spans are never persisted, by design (`src/redakt/services/audit.py`).
