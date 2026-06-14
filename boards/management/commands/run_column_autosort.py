"""
Auto-ordenação agendada das colunas (Trello-like).

Rodar 1x/dia por cron na VM, ex.:
    5 6 * * *  cd /app && python manage.py run_column_autosort

Cada coluna define a frequência (todo dia / toda semana + dia) e o critério.
O command só ordena as que estão "vencidas" no dia (a menos de --force).
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from boards.models import Column
from boards.services.column_autosort import apply_autosort, is_due


class Command(BaseCommand):
    help = "Ordena automaticamente as colunas configuradas (auto-ordenação agendada)."

    def add_arguments(self, parser):
        parser.add_argument("--column", type=int, default=None, help="Só esta coluna.")
        parser.add_argument("--force", action="store_true", help="Ignora a frequência/dia.")

    def handle(self, *args, **opts):
        now = timezone.localtime()
        today = now.date()
        qs = Column.objects.filter(is_deleted=False).exclude(autosort_freq="none")
        if opts["column"]:
            qs = qs.filter(id=opts["column"])

        total = 0
        for col in qs.select_related("board"):
            if not opts["force"] and not is_due(col, now):
                continue
            changed = apply_autosort(col)
            col.autosort_last_run = today
            col.save(update_fields=["autosort_last_run"])
            total += 1
            self.stdout.write(f"[col {col.id}] {col.name}: {changed} card(s) reordenado(s).")

        self.stdout.write(self.style.SUCCESS(f"Colunas processadas: {total}."))
