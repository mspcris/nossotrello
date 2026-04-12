#!/usr/bin/env bash
# ============================================================================
# Deploy Produção — Nossotrello
# ----------------------------------------------------------------------------
# Executa diretamente na VM (/opt/nossotrello). Puxa a branch `deploy`
# do origin, rebuilda o stack Docker e roda collectstatic + migrate.
#
# Uso manual (dentro da VM):
#   cd /opt/nossotrello
#   bash scripts/deploy.sh
#
# O mesmo fluxo roda automaticamente via GitHub Actions em
# .github/workflows/deploy.yml quando há push na branch `deploy`.
# ============================================================================

set -euo pipefail

cd /opt/nossotrello

echo "==> docker system prune"
docker system prune -af --volumes

echo "==> git sync"
git fetch origin
git reset --hard origin/deploy

echo "==> compose down"
docker compose -p nossotrello down --remove-orphans

echo "==> compose up --build"
docker compose -p nossotrello up -d --build --force-recreate

echo "==> collectstatic"
docker exec -it nossotrello-web-1 sh -lc "python manage.py collectstatic --noinput --clear"

echo "==> restart nginx"
docker compose -p nossotrello restart nginx

echo "==> migrate"
docker exec -it nossotrello-web-1 python manage.py migrate
docker exec -it nossotrello-web-1 python manage.py showmigrations boards

echo "==> done"
