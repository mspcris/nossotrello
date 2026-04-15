import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from boards.models import StoredFile


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
