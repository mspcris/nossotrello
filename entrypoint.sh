#!/bin/bash
set -e

echo "=== Entrypoint: collectstatic ==="
python manage.py collectstatic --noinput

echo "=== Entrypoint: fix_migrations (sync histórico) ==="
python manage.py fix_migrations --apply

echo "=== Entrypoint: migrate ==="
python manage.py migrate --noinput

echo "=== Entrypoint: starting gunicorn ==="
exec "$@"
