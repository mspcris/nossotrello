#!/usr/bin/env bash
# ============================================================================
# Deploy Produção — Nossotrello
# ----------------------------------------------------------------------------
# Uso na VM:
#   bash scripts/deploy.sh          # fast (default) — ~2min
#   bash scripts/deploy.sh full     # full — prune + down + rebuild — ~4min
# ============================================================================

set -euo pipefail
cd /opt/nossotrello

MODE="${1:-fast}"

echo "==> git sync"
git fetch origin
git reset --hard origin/deploy

if [ "$MODE" = "full" ]; then
  echo "==> docker system prune"
  docker system prune -af --volumes
  echo "==> compose down"
  docker compose -p nossotrello down --remove-orphans
fi

echo "==> compose up --build"
docker compose -p nossotrello up -d --build --force-recreate

echo "==> migrate"
docker exec -it nossotrello-web-1 python manage.py migrate

echo "==> repair legacy file refs"
docker exec -it nossotrello-web-1 python manage.py repair_legacy_file_refs --apply

echo "==> collectstatic"
docker exec -it nossotrello-web-1 sh -lc "python manage.py collectstatic --noinput --clear"

echo "==> done ($MODE)"
