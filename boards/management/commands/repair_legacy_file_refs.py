import hashlib
import mimetypes
import os
import re
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils._os import safe_join

from boards.models import (
    Board,
    CamilaPOP,
    Card,
    CardAttachment,
    CardLog,
    ChatSticker,
    DailyCheckIn,
    SocialPost,
    SocialPostVersion,
    StoredFile,
    UserProfile,
)


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

UUID_RE = re.compile(
    r"^[0-9a-f]{32}$|^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)


class Command(BaseCommand):
    help = "Repara referencias legadas de arquivos, convertendo-as para UUIDs de StoredFile."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Aplica as alteracoes. Sem isso, roda em dry-run.",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        touched_board_ids = set()
        grand_totals = defaultdict(int)

        for model_class, field_name in FILE_FIELDS:
            label = f"{model_class.__name__}.{field_name}"
            manager = getattr(model_class, "all_objects", model_class._base_manager)
            qs = (
                manager.exclude(**{f"{field_name}__isnull": True})
                .exclude(**{field_name: ""})
                .iterator(chunk_size=200)
            )
            stats = defaultdict(int)
            unresolved = []

            self.stdout.write(f"\n--- {label} ---")

            for obj in qs:
                field_file = getattr(obj, field_name)
                name = getattr(field_file, "name", "") or ""
                if not name or self._is_uuid(name):
                    continue

                target_id, reason = self._resolve_target(name)
                stats[f"seen_{reason}"] += 1

                if not target_id:
                    unresolved.append((obj.pk, name, reason))
                    continue

                stats["repairable"] += 1
                if apply:
                    setattr(obj, field_name, str(target_id))
                    obj.save(update_fields=[field_name])

                    board_id = self._board_id_for(obj)
                    if board_id:
                        touched_board_ids.add(board_id)

                self._maybe_log_repair(apply, label, obj.pk, name, target_id, reason)

            if apply:
                self.stdout.write(
                    f"  aplicados: {stats['repairable']} | "
                    f"ambiguous_missing={stats['seen_ambiguous_missing']} | "
                    f"missing={stats['seen_missing']}"
                )
            else:
                self.stdout.write(
                    f"  dry-run reparaveis: {stats['repairable']} | "
                    f"ambiguous_missing={stats['seen_ambiguous_missing']} | "
                    f"missing={stats['seen_missing']}"
                )

            for key, value in stats.items():
                grand_totals[f"{label}:{key}"] += value

            if unresolved:
                self.stdout.write("  exemplos nao resolvidos:")
                for pk, name, reason in unresolved[:10]:
                    self.stdout.write(f"    pk={pk} reason={reason} -> {name}")

        if apply and touched_board_ids:
            for board in Board.all_objects.filter(id__in=touched_board_ids):
                board.version += 1
                board.save(update_fields=["version"])
            self.stdout.write(f"\nBoards atualizados: {len(touched_board_ids)}")

        self.stdout.write("\nResumo final:")
        repairable = sum(
            value for key, value in grand_totals.items() if key.endswith(":repairable")
        )
        ambiguous = sum(
            value
            for key, value in grand_totals.items()
            if key.endswith(":seen_ambiguous_missing")
        )
        missing = sum(
            value for key, value in grand_totals.items() if key.endswith(":seen_missing")
        )
        self.stdout.write(
            f"  repairable={repairable} ambiguous_missing={ambiguous} missing={missing}"
        )
        if not apply:
            self.stdout.write("  modo dry-run: nada foi alterado.")

    def _resolve_target(self, name: str):
        basename = os.path.basename(name)
        matches = list(StoredFile.objects.filter(original_name=basename).only("id", "checksum"))

        if len(matches) == 1:
            return matches[0].id, "unique_name"

        if len(matches) > 1:
            checksums = {item.checksum for item in matches}
            if len(checksums) == 1:
                return matches[0].id, "duplicate_same_checksum"

            file_path = self._legacy_path(name)
            if file_path:
                stored = self._stored_file_from_path(file_path, name)
                return stored.id, "filesystem_checksum_match"

            return None, "ambiguous_missing"

        file_path = self._legacy_path(name)
        if file_path:
            stored = self._stored_file_from_path(file_path, name)
            return stored.id, "filesystem_import"

        return None, "missing"

    def _legacy_path(self, name: str):
        try:
            path = safe_join(settings.MEDIA_ROOT, name)
        except Exception:
            return None
        return path if os.path.isfile(path) else None

    def _stored_file_from_path(self, file_path: str, original_name: str) -> StoredFile:
        with open(file_path, "rb") as fh:
            data = fh.read()

        checksum = hashlib.sha256(data).hexdigest()
        stored = StoredFile.objects.filter(checksum=checksum).first()
        if stored:
            return stored

        content_type = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
        return StoredFile.objects.create(
            original_name=os.path.basename(original_name),
            content_type=content_type,
            data=data,
            size=len(data),
            checksum=checksum,
        )

    @staticmethod
    def _board_id_for(obj):
        if isinstance(obj, Board):
            return obj.id
        if isinstance(obj, Card):
            return obj.column.board_id
        if isinstance(obj, (CardAttachment, CardLog)):
            return obj.card.column.board_id
        return None

    @staticmethod
    def _is_uuid(name: str) -> bool:
        return bool(UUID_RE.match((name or "").strip()))

    def _maybe_log_repair(self, apply, label, pk, old_name, target_id, reason):
        verb = "OK" if apply else "DRY"
        self.stdout.write(
            f"  [{verb}] {label} pk={pk} {old_name} -> {target_id} ({reason})"
        )
