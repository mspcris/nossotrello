#!/usr/bin/env bash
set -euo pipefail

cd /opt/nossotrello

echo "[1/9] limpando docker..."
docker system prune -af --volumes 2>/dev/null || true

echo "[2/9] atualizando codigo..."
GIT_SSH_COMMAND='ssh -i /root/.ssh/id_ed25519_nossotrello -o IdentitiesOnly=yes' git fetch origin
git checkout -B deploy origin/deploy
git reset --hard origin/deploy

echo "[3/9] derrubando stack antiga..."
docker compose down --remove-orphans

echo "[4/9] subindo stack nova..."
docker compose up -d --build --force-recreate

echo "[5/9] aguardando PostgreSQL ficar pronto..."
for i in $(seq 1 30); do
  docker compose exec -T db pg_isready -U nossotrello -d nossotrello 2>/dev/null && break
  echo "  aguardando... ($i/30)"
  sleep 2
done

echo "[6/9] status..."
docker compose ps

echo "[7/9] coletando estaticos..."
docker exec nossotrello-web-1 python manage.py collectstatic --noinput --clear
docker compose -p nossotrello restart nginx

echo "[8/9] migracoes..."
docker exec nossotrello-web-1 python manage.py makemigrations boards
docker exec nossotrello-web-1 python manage.py migrate
docker exec nossotrello-web-1 python manage.py showmigrations boards

echo "[9/9] logs web..."
docker compose logs --tail=50 web

echo ""
echo "======================================="
echo "  DEPLOY PRODUCAO CONCLUIDO"
echo "  PostgreSQL + Redis + Gunicorn gthread"
echo "======================================="
