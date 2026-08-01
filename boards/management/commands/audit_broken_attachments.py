"""Lista anexos cujos bytes não existem mais no StoredFile.

Como isso acontecia: o storage deduplica por checksum, então o mesmo arquivo
anexado em dois cards vira UMA linha de StoredFile. Antes do soft-delete
(migration 0139, 27/07/2026), remover o anexo de um card apagava a linha de
verdade; o `django_cleanup` chamava `storage.delete()` e os bytes sumiam —
levando junto o anexo do OUTRO card, que ficava com link quebrado e o nome
"arquivo".

O `DatabaseStorage.delete` passou a recusar remoção de blob ainda referenciado,
então a conta não deve mais crescer. Esta command é para conferir isso.

    python manage.py audit_broken_attachments
"""

import uuid as _uuid
from collections import Counter

from django.core.management.base import BaseCommand


def _key(raw) -> str:
    """Chave UUID canônica, ou "" para referência legada de caminho."""
    try:
        return str(_uuid.UUID(str(raw or "").strip()))
    except (ValueError, TypeError, AttributeError):
        return ""


class Command(BaseCommand):
    help = "Aponta anexos e entradas de feed que apontam para bytes inexistentes."

    def handle(self, *args, **options):
        from boards.models import CardAttachment, CardLog, StoredFile

        atts = list(
            CardAttachment.all_objects.all().only("id", "file", "card_id", "created_at", "is_active")
        )
        keys = {k for k in (_key(a.file.name) for a in atts) if k}
        alive = set(
            map(str, StoredFile.objects.filter(id__in=list(keys)).values_list("id", flat=True))
        )

        broken = [a for a in atts if _key(a.file.name) and _key(a.file.name) not in alive]
        legacy = sum(1 for a in atts if not _key(a.file.name))

        self.stdout.write(f"anexos totais          : {len(atts)}")
        self.stdout.write(f"referência legada      : {legacy} (caminho, não UUID)")
        self.stdout.write(
            f"apontam para o vazio   : {len(broken)}"
            f"  (vivos: {sum(1 for a in broken if a.is_active)})"
        )

        if not broken:
            self.stdout.write(self.style.SUCCESS("\nNenhum anexo órfão."))
            return

        # Quantas linhas dividiam cada blob morto — é a assinatura do problema:
        # >1 significa que o arquivo estava em mais de um lugar quando morreu.
        por_chave = Counter(_key(a.file.name) for a in atts if _key(a.file.name))

        self.stdout.write("\nchave morta                            linhas  card   criado em")
        for a in sorted(broken, key=lambda x: x.created_at or 0):
            k = _key(a.file.name)
            data = a.created_at.date() if a.created_at else "?"
            self.stdout.write(f"{k}  {por_chave[k]:>6}  {a.card_id:<6} {data}")

        compartilhadas = 0
        for k in {_key(a.file.name) for a in broken}:
            cards = {l.card_id for l in CardLog.objects.filter(attachment=k).only("card_id")}
            if len(cards) > 1:
                compartilhadas += 1
                self.stdout.write(f"  {k} aparece nos cards {sorted(cards)}")

        self.stdout.write(self.style.WARNING(
            f"\n{compartilhadas} chave(s) estavam em mais de um card — "
            "confirma a remoção em cascata do blob compartilhado."
        ))
