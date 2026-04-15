import tempfile
import hashlib
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from boards.models import Board, Card, CardAttachment, Column, StoredFile


class MediaServeCompatTests(TestCase):
    def test_serves_stored_file_by_uuid(self):
        stored = StoredFile.objects.create(
            original_name="report.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            data=b"sheet-data",
            size=10,
            checksum="a" * 64,
        )

        response = self.client.get(f"/media/serve/{stored.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"sheet-data")
        self.assertEqual(response["ETag"], '"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"')

    def test_serves_legacy_reference_from_storedfile_by_unique_original_name(self):
        StoredFile.objects.create(
            original_name="legacy-report.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            data=b"legacy-data",
            size=11,
            checksum="b" * 64,
        )

        response = self.client.get("/media/serve/attachments/legacy-report.xlsx/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"legacy-data")

    def test_returns_404_for_ambiguous_legacy_original_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            StoredFile.objects.create(
                original_name="image.png",
                content_type="image/png",
                data=b"first",
                size=5,
                checksum="c" * 64,
            )
            StoredFile.objects.create(
                original_name="image.png",
                content_type="image/png",
                data=b"second",
                size=6,
                checksum="d" * 64,
            )

            with override_settings(MEDIA_ROOT=tmpdir):
                response = self.client.get("/media/serve/attachments/image.png/")

            self.assertEqual(response.status_code, 404)

    def test_falls_back_to_filesystem_for_legacy_reference(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "attachments" / "legacy.txt"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(b"legacy-fs")

            with override_settings(MEDIA_ROOT=tmpdir):
                response = self.client.get("/media/serve/attachments/legacy.txt/")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), b"legacy-fs")


class RepairLegacyFileRefsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="tester",
            email="tester@example.com",
            password="secret123",
        )
        self.board = Board.all_objects.create(name="Board teste", created_by=self.user)
        self.column = Column.objects.create(board=self.board, name="Coluna", position=1)
        self.card = Card.all_objects.create(
            title="Card teste",
            column=self.column,
            created_by=self.user,
            position=1,
        )

    def test_repairs_unique_name_match(self):
        stored = StoredFile.objects.create(
            original_name="legacy-report.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            data=b"legacy-data",
            size=11,
            checksum="e" * 64,
        )
        attachment = CardAttachment.objects.create(
            card=self.card,
            file="attachments/legacy-report.xlsx",
            description="arquivo antigo",
            created_by=self.user,
        )

        call_command("repair_legacy_file_refs", "--apply")

        attachment.refresh_from_db()
        self.board.refresh_from_db()
        self.assertEqual(attachment.file.name, str(stored.id))
        self.assertEqual(self.board.version, 1)

    def test_repairs_ambiguous_name_from_filesystem_checksum(self):
        StoredFile.objects.create(
            original_name="image.png",
            content_type="image/png",
            data=b"first",
            size=5,
            checksum="f" * 64,
        )
        expected = StoredFile.objects.create(
            original_name="image.png",
            content_type="image/png",
            data=b"second",
            size=6,
            checksum=hashlib.sha256(b"second").hexdigest(),
        )
        attachment = CardAttachment.objects.create(
            card=self.card,
            file="attachments/image.png",
            description="ambiguous",
            created_by=self.user,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "attachments" / "image.png"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(b"second")

            with override_settings(MEDIA_ROOT=tmpdir):
                call_command("repair_legacy_file_refs", "--apply")

        attachment.refresh_from_db()
        self.assertEqual(attachment.file.name, str(expected.id))

    def test_imports_missing_stored_file_from_filesystem(self):
        attachment = CardAttachment.objects.create(
            card=self.card,
            file="attachments/new-file.txt",
            description="importar",
            created_by=self.user,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "attachments" / "new-file.txt"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(b"new-file-data")

            with override_settings(MEDIA_ROOT=tmpdir):
                call_command("repair_legacy_file_refs", "--apply")

        attachment.refresh_from_db()
        stored = StoredFile.objects.get(id=attachment.file.name)
        self.assertEqual(stored.original_name, "new-file.txt")
        self.assertEqual(bytes(stored.data), b"new-file-data")
