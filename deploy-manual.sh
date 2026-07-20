#!/usr/bin/env bash
# Deploy manual de PRODUÇÃO — alternativa ao deploy.sh que NÃO mata o certbot.
#
# Por que existe: `docker system prune -af --volumes` (usado no deploy.sh) remove
# CONTAINERS PARADOS e depois as imagens que ficaram sem container. O certbot vive
# parado — só sobe para renovar certificado — então o prune apaga o container e,
# em seguida, a imagem. No `up` seguinte o compose tenta criar o certbot, não acha
# a imagem e ABORTA O DEPLOY INTEIRO:
#     Error response from daemon: No such image: certbot/certbot:latest
#
# A outra troca importante é a ORDEM. Limpar ANTES do build reclama pouco: as
# imagens antigas ainda estão em uso pelos containers de pé. Depois do build elas
# viram órfãs — é aí que o espaço realmente sai.
set -euo pipefail

cd /opt/nossotrello

echo "==> [1/5] codigo"
git fetch origin
git checkout -B deploy origin/deploy
git reset --hard origin/deploy

echo "==> [2/5] stack (--force-recreate ja troca os containers; sem 'down' o fora do ar e menor)"
docker compose -p nossotrello up -d --build --force-recreate

echo "==> [3/5] migracoes"
docker exec nossotrello-web-1 python manage.py migrate
docker exec nossotrello-web-1 python manage.py showmigrations boards

echo "==> [4/5] estaticos"
docker exec nossotrello-web-1 sh -lc "python manage.py collectstatic --noinput --clear"
docker compose -p nossotrello restart nginx

echo "==> [5/5] limpeza (segura: nunca remove imagem COM TAG nem container parado)"
# `image prune` SEM -a: so imagens sem tag — as versoes velhas que cada rebuild
# deixa para tras. Imagem com tag (certbot/certbot:latest) nunca entra na conta.
docker image prune -f || true
# O cache de camadas costuma liberar mais que o `system prune` inteiro.
docker builder prune -af || true
docker system df

echo ""
echo "======================================="
echo "  DEPLOY CONCLUIDO (certbot preservado)"
echo "======================================="
echo ""
echo "Se algum dia precisar da faxina pesada, o pull do certbot e OBRIGATORIO:"
echo "    docker system prune -af --volumes && docker pull certbot/certbot:latest"
