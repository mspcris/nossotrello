#!/usr/bin/env bash
set -euo pipefail

cd /opt/nossotrello

echo "[1/9] limpando docker..."
docker system prune -af --volumes

echo "[2/9] atualizando codigo..."
GIT_SSH_COMMAND='ssh -i /root/.ssh/id_ed25519_nossotrello -o IdentitiesOnly=yes' git fetch origin
git checkout -B deploy origin/deploy
git reset --hard origin/deploy

echo "[3/9] derrubando stack antiga..."
docker compose down --remove-orphans

echo "[4/9] subindo stack nova..."
docker compose up -d --build --force-recreate

echo "[5/9] status..."
docker compose ps

echo "[6/9] logs web..."
docker compose logs --tail=200 web

echo "[7/9] logs nginx..."
docker compose logs --tail=120 nginx

echo "[8/9] coletando estaticos..."
docker exec -it nossotrello-web-1 sh -lc "python manage.py collectstatic --noinput --clear"
docker compose -p nossotrello restart nginx

echo "[9/9] migracoes..."
docker exec -it nossotrello-web-1 python manage.py makemigrations boards
docker exec -it nossotrello-web-1 python manage.py migrate
docker exec -it nossotrello-web-1 python manage.py showmigrations boards

echo "deploy producao concluido"
