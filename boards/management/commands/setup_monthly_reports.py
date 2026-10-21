"""
Rollout da automação "Entrega mensal de relatório" nos quadros dos postos.

    python manage.py setup_monthly_reports --boards 34,35,36,37,38,39,40,41 \
        --recipient leonardo@camim.com.br [--column "Relatórios Empresariais"] \
        [--remind-now] [--dry-run]

Para cada quadro: acha a coluna (nome contém "relat" + "empresar" por padrão),
corrige a grafia para "Relatórios Empresariais", cria/reativa a regra
attach -> monthly_report e monta o livro-razão de cada card a partir dos anexos
existentes (mês pelo nome do arquivo, senão pela data do upload). Meses sem
anexo ficam PENDENTES; com --remind-now a cobrança sai na hora (um e-mail por
card, gestores do Hesk + cópia ao destinatário).

Idempotente: rodar de novo não duplica regra nem entradas.
"""
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from boards.models import Board, Card, Column, ColumnAutomation
from boards.services import monthly_report as mr


class Command(BaseCommand):
    help = "Cria a automação de entrega mensal nas colunas de relatório dos quadros."

    def add_arguments(self, parser):
        parser.add_argument("--boards", required=True, help="ids separados por vírgula")
        parser.add_argument("--recipient", default="leonardo@camim.com.br")
        parser.add_argument("--column", default="", help="nome exato da coluna (opcional)")
        parser.add_argument("--day", type=int, default=15)
        parser.add_argument("--no-ai", action="store_true")
        parser.add_argument("--ai-instructions", default=None,
                            help="o que o arquivo precisa conter (orienta a IA); omitido = não mexe")
        parser.add_argument("--start-month", default="",
                            help="YYYY-MM: cobra deste mês em diante (sem ele, desde o 1º anexo achado)")
        parser.add_argument("--remind-now", action="store_true", help="cobra os meses vencidos já")
        parser.add_argument("--dry-run", action="store_true")

    def _find_column(self, board, name):
        qs = Column.objects.filter(board=board, is_deleted=False)
        if name:
            # nome explícito: SÓ a coluna exata — nunca cair na heurística e mexer
            # na regra de outra coluna (ex.: "Relatórios Empresariais")
            return qs.filter(name__iexact=name).first()
        for c in qs:
            n = (c.name or "").lower()
            # aceita a grafia errada "Reloatórios" que existe em produção
            if "empresar" in n and (n.startswith("rel") or "relat" in n):
                return c
        return None

    def handle(self, *args, **opts):
        ids = [int(x) for x in opts["boards"].split(",") if x.strip().isdigit()]
        if not ids:
            raise CommandError("--boards vazio")
        dry = opts["dry_run"]
        start = (opts["start_month"] or "").strip()
        if start and not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", start):
            raise CommandError("--start-month precisa ser YYYY-MM")

        for bid in ids:
            board = Board.all_objects.filter(id=bid).first()
            if board is None:
                self.stderr.write(f"board {bid}: não existe")
                continue
            col = self._find_column(board, opts["column"])
            if col is None:
                self.stderr.write(f"board {bid} {board.name}: coluna de relatórios não encontrada")
                continue

            with transaction.atomic():
                if col.name != "Relatórios Empresariais" and "empresar" in col.name.lower():
                    self.stdout.write(f"  coluna {col.id}: '{col.name}' -> 'Relatórios Empresariais'")
                    if not dry:
                        col.name = "Relatórios Empresariais"
                        col.save(update_fields=["name"])

                rule = ColumnAutomation.objects.filter(column=col, action="monthly_report").first()
                params = {
                    "day": opts["day"],
                    "recipient_email": opts["recipient"].strip().lower(),
                    "ai_validate": not opts["no_ai"],
                }
                if opts["ai_instructions"] is not None:
                    params["ai_instructions"] = opts["ai_instructions"].strip()
                if start:
                    params["start_month"] = start
                if rule is None:
                    self.stdout.write(f"board {bid} {board.name}: criando regra na coluna {col.id}")
                    if dry:
                        continue
                    rule = ColumnAutomation.objects.create(
                        column=col, trigger="attach", action="monthly_report",
                        params={"extra_user_ids": [], "ai_instructions": "", "posto_nome": "", **params},
                    )
                else:
                    self.stdout.write(f"board {bid} {board.name}: regra {rule.id} já existe (atualizando)")
                    if not dry:
                        merged = dict(rule.params or {})
                        merged.update(params)
                        rule.params = merged
                        rule.trigger = "attach"
                        rule.is_active = True
                        rule.save(update_fields=["params", "trigger", "is_active"])

                if dry:
                    continue

                cards = Card.objects.filter(column=col, is_archived=False, counter_mode="")
                earliest = None
                for card in cards:
                    info = mr.seed_card(rule, card)
                    self.stdout.write(
                        f"    card {card.id} {card.title[:50]!r}: novas={info['created']} "
                        f"pendentes={info['pending'] or '-'} entrega={info['due']:%d/%m/%Y}"
                    )
                    first = rule.monthly_entries.filter(card=card).order_by("month").values_list("month", flat=True).first()
                    if first and (earliest is None or first < earliest):
                        earliest = first
                if earliest and not start:
                    p = dict(rule.params or {})
                    p["start_month"] = earliest.strftime("%Y-%m")
                    rule.params = p
                    rule.save(update_fields=["params"])

        mr.invalidate_cache()
        if opts["remind_now"] and not dry:
            stats = mr.run_scheduler()
            self.stdout.write(self.style.SUCCESS(f"Cobranças enviadas: {stats['reminded']}"))
        self.stdout.write(self.style.SUCCESS("ok"))
