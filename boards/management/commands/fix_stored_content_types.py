"""Reclassifica StoredFile que ficou com content_type genérico.

Arquivo salvo sem extensão no nome (gravador de tela, "video-2026-08-01_12.03.56")
chega com `application/octet-stream`: o navegador não tem como adivinhar. O
`file_meta` então classifica como arquivo comum e o anexo perde miniatura,
player de vídeo e conversão.

O `DatabaseStorage` já resolve isso no upload; esta command é para as linhas
que entraram antes. Lê só o cabeçalho de cada blob (substring no banco, nunca o
arquivo inteiro) e reescreve o content_type quando os bytes dizem outra coisa.

    python manage.py fix_stored_content_types            # simulação
    python manage.py fix_stored_content_types --apply
"""

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db.models.expressions import RawSQL

from boards.services.file_sniff import _WEAK_TYPES, sniff_content_type

_HEAD = 4096


class Command(BaseCommand):
    help = "Corrige content_type de StoredFile salvo como application/octet-stream."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Grava as correções (sem isso, só lista o que mudaria).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Processa no máximo N linhas (0 = todas).",
        )

    def handle(self, *args, **options):
        from boards.models import StoredFile

        apply_changes = options["apply"]
        limit = options["limit"] or 0

        weak = [t for t in _WEAK_TYPES if t]
        qs = (
            StoredFile.objects
            .filter(content_type__in=weak + [""])
            .annotate(head=RawSQL("substring(data from 1 for %s)", (_HEAD,)))
            .only("id", "original_name", "content_type")
            .order_by("id")
        )
        if limit:
            qs = qs[:limit]

        seen = fixed = 0
        for row in qs.iterator(chunk_size=200):
            seen += 1
            guess = sniff_content_type(bytes(row.head or b""))
            if not guess or guess == row.content_type:
                continue

            fixed += 1
            self.stdout.write(
                f"{row.id}  {row.original_name!r}  "
                f"{row.content_type or '(vazio)'} -> {guess}"
            )

            if apply_changes:
                StoredFile.objects.filter(id=row.id).update(content_type=guess)
                # file_meta memoiza (name, content_type) por 7 dias — sem
                # limpar, a interface continuaria mostrando o tipo antigo.
                try:
                    cache.delete(f"sfmeta:{row.id}")
                except Exception:
                    pass

        verbo = "corrigidos" if apply_changes else "corrigiríveis"
        self.stdout.write(self.style.SUCCESS(
            f"\n{seen} analisados, {fixed} {verbo}."
            + ("" if apply_changes else "  (rode com --apply para gravar)")
        ))
