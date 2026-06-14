"""
Automação 'card parado X dias' (Trello-like).

Rodar 1x/dia por cron na VM, ex.:
    10 6 * * *  cd /app && python manage.py run_stale_automations

Para cada regra com gatilho 'stale', aplica a ação (mover, e-mail, etc.) aos
cards que estão há >= X dias na lista. Idempotente: re-arma o cronômetro
(column_since) após aplicar.
"""
from django.core.management.base import BaseCommand

from boards.services.column_automation import run_stale_triggers


class Command(BaseCommand):
    help = "Aplica as automações de 'card parado X dias' (gatilho stale)."

    def handle(self, *args, **opts):
        affected = run_stale_triggers()
        self.stdout.write(self.style.SUCCESS(f"Cards afetados: {affected}."))
