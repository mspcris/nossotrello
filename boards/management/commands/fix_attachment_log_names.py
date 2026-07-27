"""Troca a chave UUID pelo nome real do arquivo nos logs antigos de anexo.

Até 07/2026 o texto do log era montado com `attachment.file.name`, que no
DatabaseStorage é a chave UUID do StoredFile — o feed mostrava
"adicionou um anexo: 79739e52-1334-…" e ninguém reconhecia o próprio arquivo.
Uploads novos já gravam o nome certo; este comando arruma o histórico.

Uso:
    python manage.py fix_attachment_log_names            # simula (dry-run)
    python manage.py fix_attachment_log_names --apply    # grava
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils.html import escape

from boards.models import CardLog
from boards.services.file_meta import display_name


class Command(BaseCommand):
    help = "Substitui o UUID do storage pelo nome original nos logs de anexo antigos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Grava as alterações (sem esta flag, apenas simula).",
        )

    def handle(self, *args, **options):
        apply = bool(options.get("apply"))

        qs = CardLog.objects.exclude(attachment="").exclude(attachment=None)

        checked = fixed = 0
        for log in qs.iterator(chunk_size=200):
            checked += 1

            raw = (getattr(log.attachment, "name", "") or "")
            key = raw.split("/")[-1]
            if not key:
                continue

            real = display_name(log.attachment)
            if not real or real == key:
                continue

            content = log.content or ""
            text = log.content_text or ""
            if key not in content and key not in text:
                continue

            log.content = content.replace(key, escape(real))
            log.content_text = text.replace(key, real)

            if apply:
                log.save(update_fields=["content", "content_text"])
            fixed += 1
            self.stdout.write(f"  log {log.id}: {key} -> {real}")

        verb = "corrigidos" if apply else "seriam corrigidos"
        self.stdout.write(self.style.SUCCESS(
            f"{checked} logs com anexo verificados; {fixed} {verb}."
        ))
        if not apply and fixed:
            self.stdout.write("Rode de novo com --apply para gravar.")
