"""
Sincroniza as caixas IMAP configuradas (feature "Criar Card From Email"),
criando cards na coluna-alvo de cada quadro.

Rodar por cron na VM, ex. a cada 5 min:
    */5 * * * * cd /app && python manage.py sync_email_cards

Cada config tem seu próprio intervalo (sync_interval_minutes); o command só
processa as que já estão "vencidas" (a menos de --force).
"""
from django.core.management.base import BaseCommand

from boards.models import BoardEmailIngest
from boards.services.email_ingest import sync_one


class Command(BaseCommand):
    help = "Cria cards a partir de caixas IMAP configuradas (Criar Card From Email)."

    def add_arguments(self, parser):
        parser.add_argument("--board", type=int, default=None, help="Só esta board.")
        parser.add_argument("--force", action="store_true", help="Ignora o intervalo.")

    def handle(self, *args, **opts):
        qs = (
            BoardEmailIngest.objects.filter(is_active=True)
            .select_related("target_column", "board")
        )
        if opts["board"]:
            qs = qs.filter(board_id=opts["board"])

        total = 0
        for cfg in qs:
            if not opts["force"] and not cfg.is_due():
                continue
            created, err = sync_one(cfg)
            total += created
            if err:
                self.stderr.write(f"[board {cfg.board_id}] erro: {err}")
            else:
                self.stdout.write(f"[board {cfg.board_id}] {created} card(s).")

        self.stdout.write(self.style.SUCCESS(f"Total: {total} card(s) criado(s)."))
