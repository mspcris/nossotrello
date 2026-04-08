"""
Management command que corrige o histórico de migrations no banco.

Problema raiz:
  Migrations foram aplicadas fora do Docker (pelo web app) mas o
  django_migrations não reflete isso. Quando o container reinicia,
  `migrate` tenta criar tabelas/colunas que já existem → erro.

O que este comando faz:
  1. Remove registros fantasma (DB tem, mas arquivo não existe)
  2. Para migrations faltantes (disco mas não DB):
     a) Introspecciona o banco e verifica se as operações já estão aplicadas
     b) Se TODAS as operações já existem no schema → fake-aplica
        (respeitando ordem topológica de dependências)
     c) Se há operações pendentes reais → deixa para `migrate`
  3. Reporta o resultado

Uso:
  python manage.py fix_migrations          # dry-run (só mostra)
  python manage.py fix_migrations --apply  # aplica correções
"""
import os
from importlib import import_module

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection, migrations as mig_module


def _get_existing_tables():
    """Retorna set de tabelas existentes no banco."""
    with connection.cursor() as cursor:
        return set(connection.introspection.table_names(cursor))


def _get_existing_columns(table_name):
    """Retorna set de colunas existentes em uma tabela."""
    try:
        with connection.cursor() as cursor:
            return {
                col.name
                for col in connection.introspection.get_table_description(cursor, table_name)
            }
    except Exception:
        return set()


def _migration_already_applied(app_label, migration_module):
    """
    Verifica se TODAS as operações de uma migration já estão refletidas
    no schema do banco. Se sim, é seguro fake-aplicar.
    """
    ops = getattr(migration_module.Migration, "operations", [])
    if not ops:
        return True  # merge ou no-op

    existing_tables = _get_existing_tables()

    for op in ops:
        # CreateModel → tabela já existe?
        if isinstance(op, mig_module.CreateModel):
            table = f"{app_label}_{op.name.lower()}"
            if table not in existing_tables:
                return False

        # AddField → coluna já existe?
        elif isinstance(op, mig_module.AddField):
            table = f"{app_label}_{op.model_name.lower()}"
            if table not in existing_tables:
                return False
            cols = _get_existing_columns(table)
            col_name = op.name
            if col_name not in cols and f"{col_name}_id" not in cols:
                return False

        # RemoveField → coluna já não existe?
        elif isinstance(op, mig_module.RemoveField):
            table = f"{app_label}_{op.model_name.lower()}"
            if table in existing_tables:
                cols = _get_existing_columns(table)
                if op.name in cols or f"{op.name}_id" in cols:
                    return False

        # RenameField → nova coluna existe?
        elif isinstance(op, mig_module.RenameField):
            table = f"{app_label}_{op.model_name.lower()}"
            if table not in existing_tables:
                return False
            cols = _get_existing_columns(table)
            if op.new_name not in cols and f"{op.new_name}_id" not in cols:
                return False

        # AlterField → coluna existe
        elif isinstance(op, mig_module.AlterField):
            table = f"{app_label}_{op.model_name.lower()}"
            if table not in existing_tables:
                return False
            cols = _get_existing_columns(table)
            if op.name not in cols and f"{op.name}_id" not in cols:
                return False

        # AddIndex / RenameIndex → tabela existe é suficiente
        elif isinstance(op, mig_module.AddIndex):
            table = f"{app_label}_{op.model_name.lower()}"
            if table not in existing_tables:
                return False

        elif isinstance(op, mig_module.RenameIndex):
            table = f"{app_label}_{op.model_name.lower()}"
            if table not in existing_tables:
                return False

        # RemoveIndex → sempre safe
        elif isinstance(op, mig_module.RemoveIndex):
            pass

        # AlterModelOptions, AlterModelTable, etc → schema-safe
        elif isinstance(op, (mig_module.AlterModelOptions,
                            mig_module.AlterModelTable,
                            mig_module.AlterUniqueTogether,
                            mig_module.AlterIndexTogether)):
            pass

        # RenameModel → tabela nova existe?
        elif isinstance(op, mig_module.RenameModel):
            new_table = f"{app_label}_{op.new_name.lower()}"
            if new_table not in existing_tables:
                return False

        # DeleteModel → tabela já não existe?
        elif isinstance(op, mig_module.DeleteModel):
            table = f"{app_label}_{op.name.lower()}"
            if table in existing_tables:
                return False

        # RunPython, RunSQL → assumir aplicado se restante bate
        elif isinstance(op, (mig_module.RunPython, mig_module.RunSQL)):
            pass

        # SeparateDatabaseAndState → safe
        elif isinstance(op, mig_module.SeparateDatabaseAndState):
            pass

        # Tipo desconhecido → conservador, não fake
        else:
            return False

    return True


def _get_dependencies(app_label, app_config, name):
    """Retorna nomes de migrations do mesmo app das quais esta depende."""
    try:
        mod = import_module(f"{app_config.name}.migrations.{name}")
        deps = set()
        for dep_app, dep_name in getattr(mod.Migration, "dependencies", []):
            if dep_app == app_label:
                deps.add(dep_name)
        return deps
    except Exception:
        return set()


def _topological_sort(names, deps_map):
    """Ordena migrations respeitando dependências."""
    sorted_list = []
    visited = set()
    visiting = set()

    def visit(name):
        if name in visited:
            return
        if name in visiting:
            return  # ciclo, ignorar
        visiting.add(name)
        for dep in deps_map.get(name, set()):
            if dep in names:
                visit(dep)
        visiting.discard(name)
        visited.add(name)
        sorted_list.append(name)

    for name in sorted(names):
        visit(name)
    return sorted_list


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
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT name FROM django_migrations WHERE app = %s ORDER BY name",
                    [app_label],
                )
                db_names = {row[0] for row in cursor.fetchall()}
        except Exception:
            self.stdout.write(self.style.SUCCESS(
                "  Banco novo (sem django_migrations). Rode: python manage.py migrate"
            ))
            return

        # 2) Migrations no disco
        app_config = apps.get_app_config(app_label)
        mig_mod = import_module(f"{app_config.name}.migrations")
        migrations_dir = os.path.dirname(mig_mod.__file__)
        disk_names = set()
        for fname in os.listdir(migrations_dir):
            if fname.endswith(".py") and fname != "__init__.py":
                disk_names.add(fname[:-3])

        # 3) Fantasmas e faltantes
        ghosts = db_names - disk_names
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

        # Classificar faltantes
        safe_to_fake = set()
        real_missing = set()
        for name in missing:
            try:
                mod = import_module(f"{app_config.name}.migrations.{name}")
                if _migration_already_applied(app_label, mod):
                    safe_to_fake.add(name)
                else:
                    real_missing.add(name)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"    Erro ao analisar {name}: {e}"))
                real_missing.add(name)

        if safe_to_fake:
            self.stdout.write(self.style.NOTICE(
                "  JÁ APLICADAS no schema (serão registradas no histórico):"
            ))
            for name in sorted(safe_to_fake):
                self.stdout.write(f"    ✓ {name}")
            self.stdout.write("")

        if real_missing:
            self.stdout.write(self.style.WARNING(
                "  PENDENTES REAIS (precisam de migrate normal):"
            ))
            for name in sorted(real_missing):
                self.stdout.write(f"    ! {name}")
            self.stdout.write("")

        if not ghosts and not safe_to_fake and not real_missing:
            self.stdout.write(self.style.SUCCESS("  ✓ Tudo ok! Nenhuma correção necessária."))
            return

        if not apply:
            self.stdout.write(
                self.style.WARNING("  Dry-run. Rode com --apply para aplicar.")
            )
            return

        # Aplicar
        from django.utils import timezone

        with connection.cursor() as cursor:
            # Remover fantasmas
            for name in sorted(ghosts):
                cursor.execute(
                    "DELETE FROM django_migrations WHERE app = %s AND name = %s",
                    [app_label, name],
                )
                self.stdout.write(self.style.SUCCESS(f"  REMOVIDO fantasma: {name}"))

            # Registrar safe_to_fake em ordem topológica (dependências primeiro)
            if safe_to_fake:
                deps_map = {}
                for name in safe_to_fake:
                    deps_map[name] = _get_dependencies(app_label, app_config, name)

                ordered = _topological_sort(safe_to_fake, deps_map)
                now = timezone.now().isoformat()

                for name in ordered:
                    # Verificar que todas as dependências estão no DB
                    deps = deps_map.get(name, set())
                    all_deps_ok = all(
                        d in db_names or d in safe_to_fake
                        for d in deps
                    )
                    if not all_deps_ok:
                        self.stdout.write(self.style.WARNING(
                            f"  PULADO (deps faltantes): {name}"
                        ))
                        continue

                    cursor.execute(
                        "INSERT INTO django_migrations (app, name, applied) "
                        "VALUES (%s, %s, %s)",
                        [app_label, name, now],
                    )
                    db_names.add(name)  # atualiza para checagem das próximas
                    self.stdout.write(self.style.SUCCESS(f"  REGISTRADO: {name}"))

        self.stdout.write("")
        if real_missing:
            self.stdout.write(self.style.WARNING(
                "  Agora rode: python manage.py migrate"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                "  ✓ Histórico sincronizado! migrate deve funcionar sem erros."
            ))
