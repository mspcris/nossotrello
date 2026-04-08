"""
Management command que corrige o histórico de migrations no banco.

Problema raiz:
  O .gitignore excluía */migrations/*.py, fazendo com que `makemigrations`
  rodado no Docker criasse arquivos que nunca iam para o git. Na próxima
  rebuild, esses arquivos sumiam mas os registros em django_migrations
  permaneciam, quebrando o grafo.

O que este comando faz:
  1. Remove registros fantasma (DB tem, mas arquivo não existe)
  2. Fake-aplica migrations que existem no disco mas não no DB
     (quando todas as anteriores já estão aplicadas)
  3. Reporta o resultado

Uso:
  python manage.py fix_migrations          # dry-run (só mostra)
  python manage.py fix_migrations --apply  # aplica correções
"""
import os
from importlib import import_module

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Corrige inconsistências no histórico de migrations (fantasmas e faltantes)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Aplica as correções (sem --apply é dry-run)",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        app_label = "boards"

        # 1) Migrations no banco
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name FROM django_migrations WHERE app = %s ORDER BY name",
                [app_label],
            )
            db_names = {row[0] for row in cursor.fetchall()}

        # 2) Migrations no disco
        app_config = apps.get_app_config(app_label)
        mod = import_module(f"{app_config.name}.migrations")
        migrations_dir = os.path.dirname(mod.__file__)
        disk_names = set()
        for fname in os.listdir(migrations_dir):
            if fname.endswith(".py") and fname != "__init__.py":
                disk_names.add(fname[:-3])  # remove .py

        # 3) Fantasmas: no DB mas sem arquivo
        ghosts = db_names - disk_names
        # 4) Faltantes: arquivo existe mas não no DB
        missing = disk_names - db_names

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"  fix_migrations ({app_label})")
        self.stdout.write(f"{'='*60}")
        self.stdout.write(f"  Migrations no banco:  {len(db_names)}")
        self.stdout.write(f"  Migrations no disco:  {len(disk_names)}")
        self.stdout.write(f"  Fantasmas (DB only):  {len(ghosts)}")
        self.stdout.write(f"  Faltantes (disk only): {len(missing)}")
        self.stdout.write("")

        if ghosts:
            self.stdout.write(self.style.WARNING("  FANTASMAS (serão removidas do DB):"))
            for name in sorted(ghosts):
                self.stdout.write(f"    - {name}")
            self.stdout.write("")

        if missing:
            self.stdout.write(self.style.NOTICE("  FALTANTES (serão fake-aplicadas):"))
            for name in sorted(missing):
                self.stdout.write(f"    + {name}")
            self.stdout.write("")

        if not ghosts and not missing:
            self.stdout.write(self.style.SUCCESS("  Tudo ok! Nenhuma correção necessária."))
            return

        if not apply:
            self.stdout.write(
                self.style.WARNING(
                    "  Dry-run. Rode com --apply para aplicar as correções."
                )
            )
            return

        # Aplicar
        with connection.cursor() as cursor:
            for name in sorted(ghosts):
                cursor.execute(
                    "DELETE FROM django_migrations WHERE app = %s AND name = %s",
                    [app_label, name],
                )
                self.stdout.write(self.style.SUCCESS(f"  REMOVIDO: {name}"))

            for name in sorted(missing):
                cursor.execute(
                    "INSERT INTO django_migrations (app, name, applied) "
                    "VALUES (%s, %s, NOW())",
                    [app_label, name],
                )
                self.stdout.write(self.style.SUCCESS(f"  FAKE-APLICADO: {name}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("  Correções aplicadas com sucesso!"))
        self.stdout.write("  Agora rode: python manage.py migrate")
