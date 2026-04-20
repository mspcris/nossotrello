# boards/management/commands/embed_cards.py
"""
Backfill / regeração de embeddings de cards.

Uso:
    python manage.py embed_cards                  # só cards sem embedding
    python manage.py embed_cards --force          # regenera todos (ignora hash)
    python manage.py embed_cards --limit 200      # limita a 200 cards
    python manage.py embed_cards --only-active    # ignora arquivados/excluídos
    python manage.py embed_cards --sleep 0.2      # pausa entre chamadas à API
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from boards.models import Card, CardEmbedding
from boards.services.card_similarity import embed_card


class Command(BaseCommand):
    help = "Gera embeddings dos cards (inclui arquivados e excluídos por padrão)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="Regenera embeddings mesmo se o hash não mudou.")
        parser.add_argument("--limit", type=int, default=0,
                            help="Máximo de cards a processar (0 = sem limite).")
        parser.add_argument("--only-active", action="store_true",
                            help="Apenas cards ativos (ignora arquivados e excluídos).")
        parser.add_argument("--sleep", type=float, default=0.0,
                            help="Sleep em segundos entre chamadas à API.")
        parser.add_argument("--verbose", action="store_true",
                            help="Loga cada card processado.")

    def handle(self, *args, **opts):
        force = bool(opts.get("force"))
        limit = int(opts.get("limit") or 0)
        only_active = bool(opts.get("only_active"))
        sleep_s = float(opts.get("sleep") or 0.0)
        verbose = bool(opts.get("verbose"))

        if only_active:
            qs = Card.objects.all()
        else:
            qs = Card.all_objects.all()

        qs = qs.select_related("column", "column__board").order_by("-id")

        if not force:
            embedded_ids = set(CardEmbedding.objects.values_list("card_id", flat=True))
            qs = qs.exclude(id__in=embedded_ids)

        total = qs.count()
        if limit:
            total = min(total, limit)
            qs = qs[:limit]

        self.stdout.write(self.style.NOTICE(
            f"Processando {total} cards (force={force}, only_active={only_active})…"
        ))

        ok = 0
        fail = 0
        skipped = 0

        for i, card in enumerate(qs.iterator(chunk_size=100), start=1):
            try:
                res = embed_card(card, force=force)
                if res is None:
                    skipped += 1
                    if verbose:
                        self.stdout.write(
                            f"[{i}/{total}] pulou card={card.id} ({(card.title or '')[:40]!r})"
                        )
                else:
                    ok += 1
                    if verbose:
                        self.stdout.write(
                            f"[{i}/{total}] ok card={card.id} ({(card.title or '')[:40]!r})"
                        )
            except Exception as e:
                fail += 1
                self.stderr.write(self.style.WARNING(
                    f"[{i}/{total}] falhou card={card.id}: {e}"
                ))

            if sleep_s > 0:
                time.sleep(sleep_s)

        self.stdout.write(self.style.SUCCESS(
            f"OK: ok={ok} fail={fail} skipped={skipped}"
        ))
