# boards/management/commands/migrate_files_to_db.py
"""
Management command que migra TODOS os arquivos do filesystem (media/)
para o banco de dados (StoredFile), atualizando os campos dos models.

Uso:
    python manage.py migrate_files_to_db          # executa
    python manage.py migrate_files_to_db --dry-run # apenas lista o que faria
"""

import hashlib
import mimetypes

from django.core.management.base import BaseCommand
from django.db import transaction

from boards.models import (
    Board,
    Card,
    CardAttachment,
    CardLog,
    CamilaPOP,
    ChatSticker,
    DailyCheckIn,
    SocialPost,
    SocialPostVersion,
    StoredFile,
    UserProfile,
)

# Mapa: (Model, campo_arquivo)
FILE_FIELDS = [
    (Board, "image"),
    (Board, "background_image"),
    (Card, "cover_image"),
    (CardLog, "attachment"),
    (CardAttachment, "file"),
    (UserProfile, "avatar"),
    (UserProfile, "cover_photo"),
    (SocialPost, "photo"),
    (SocialPost, "video"),
    (SocialPostVersion, "photo"),
    (SocialPostVersion, "video"),
    (DailyCheckIn, "lunch_photo"),
    (ChatSticker, "image"),
    (CamilaPOP, "pdf_file"),
]


class Command(BaseCommand):
    help = "Migra arquivos do filesystem (media/) para o banco (StoredFile)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Apenas lista o que seria migrado, sem alterar nada",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        total_migrated = 0
        total_skipped = 0
        total_errors = 0

        for model_class, field_name in FILE_FIELDS:
            model_label = f"{model_class.__name__}.{field_name}"
            self.stdout.write(f"\n--- {model_label} ---")

            qs = model_class.objects.all()
            count = 0

            for obj in qs.iterator(chunk_size=100):
                field_file = getattr(obj, field_name)

                # Pula se campo vazio
                if not field_file or not field_file.name:
                    continue

                name = field_file.name

                # Pula se já é um UUID (já migrado)
                if self._is_uuid(name):
                    total_skipped += 1
                    continue

                if dry_run:
                    self.stdout.write(f"  [DRY-RUN] {model_label} pk={obj.pk} → {name}")
                    count += 1
                    continue

                try:
                    data = field_file.read()
                    if not data:
                        self.stderr.write(f"  [VAZIO] {model_label} pk={obj.pk} → {name}")
                        total_errors += 1
                        continue

                    checksum = hashlib.sha256(data).hexdigest()
                    content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
                    original_name = name.split("/")[-1] if "/" in name else name

                    # Deduplicação
                    stored = StoredFile.objects.filter(checksum=checksum).first()
                    if not stored:
                        stored = StoredFile.objects.create(
                            original_name=original_name,
                            content_type=content_type,
                            data=data,
                            size=len(data),
                            checksum=checksum,
                        )

                    # Atualiza campo para apontar pro UUID
                    setattr(obj, field_name, str(stored.id))
                    obj.save(update_fields=[field_name])

                    count += 1
                    self.stdout.write(f"  [OK] pk={obj.pk} {name} → {stored.id}")

                except FileNotFoundError:
                    self.stderr.write(f"  [ARQUIVO NÃO ENCONTRADO] {model_label} pk={obj.pk} → {name}")
                    total_errors += 1
                except Exception as e:
                    self.stderr.write(f"  [ERRO] {model_label} pk={obj.pk} → {name}: {e}")
                    total_errors += 1

            total_migrated += count
            self.stdout.write(f"  {count} arquivo(s) {'listado(s)' if dry_run else 'migrado(s)'}")

        self.stdout.write(f"\n{'=' * 50}")
        self.stdout.write(f"Total migrado: {total_migrated}")
        self.stdout.write(f"Total já migrado (skip): {total_skipped}")
        self.stdout.write(f"Total erros: {total_errors}")

        if dry_run:
            self.stdout.write("\n⚠ DRY-RUN: nada foi alterado.")

    @staticmethod
    def _is_uuid(name: str) -> bool:
        """Verifica se o name do campo já é um UUID (já migrado)."""
        import re
        clean = name.replace("-", "")
        return bool(re.match(r"^[0-9a-f]{32}$", clean))
