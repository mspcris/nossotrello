"""
Automação "Entrega mensal de relatório" — cobrança do dia 15 + retry da IA.

Roda no loop do `scheduler` (docker-compose) a cada 10 min. Idempotente: cada
mês vencido sem anexo é cobrado UMA vez (reminded_at); um e-mail por card
listando todos os meses em atraso, para os gestores do posto (cadastro do Hesk)
com cópia ao destinatário da regra.
"""
from django.core.management.base import BaseCommand

from boards.services.monthly_report import run_scheduler


class Command(BaseCommand):
    help = "Cobra relatórios mensais vencidos e reprocessa validações de IA presas."

    def handle(self, *args, **opts):
        stats = run_scheduler()
        self.stdout.write(self.style.SUCCESS(
            f"Cobranças: {stats['reminded']} · IA reprocessada: {stats['retried']}."
        ))
