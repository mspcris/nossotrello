#!/usr/bin/env bash
# ============================================================
# Migra dados do SQLite para PostgreSQL (executar 1x no servidor)
#
# Uso:
#   cd /opt/nossotrello
#   bash migrate_sqlite_to_pg.sh
#
# Pré-requisitos:
#   - docker compose up -d (stack rodando com PostgreSQL)
#   - SQLite em ./data/sqlite/db.sqlite3
# ============================================================
set -euo pipefail

cd /opt/nossotrello

WEB="nossotrello-web-1"

echo "=== MIGRAÇÃO SQLite → PostgreSQL ==="
echo ""

# 1) Garantir que as tabelas existem no PostgreSQL
echo "[1/4] Criando schema no PostgreSQL..."
docker exec -it $WEB python manage.py migrate --run-syncdb

# 2) Dump dos dados do SQLite (excluindo contenttypes/auth.permission para evitar conflitos)
echo "[2/4] Exportando dados do SQLite..."
docker exec -it $WEB python -c "
import os, django
os.environ['DB_ENGINE'] = ''  # força SQLite
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nossotrello.settings')
django.setup()
from django.core.management import call_command
call_command(
    'dumpdata',
    '--natural-foreign',
    '--natural-primary',
    '--exclude=contenttypes',
    '--exclude=auth.permission',
    '--indent=2',
    '-o', '/tmp/sqlite_dump.json',
)
print('Dump concluido: /tmp/sqlite_dump.json')
"

# 3) Carregar no PostgreSQL
echo "[3/4] Importando dados no PostgreSQL..."
docker exec -it $WEB python manage.py loaddata /tmp/sqlite_dump.json

echo "[4/4] Limpando dump temporario..."
docker exec -it $WEB rm -f /tmp/sqlite_dump.json

echo ""
echo "=== MIGRAÇÃO CONCLUÍDA ==="
echo "Verifique os dados acessando a aplicação."
echo "Depois de confirmar, pode remover o volume SQLite."
