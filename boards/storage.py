# boards/storage.py
"""
DatabaseStorage — Custom Django storage backend that saves files
as binary (bytea) in PostgreSQL via the StoredFile model.

Drop-in replacement: every FileField / ImageField keeps working
because Django calls storage.save(), storage.url(), etc.
"""

import hashlib
import uuid
from io import BytesIO

from django.core.files.base import ContentFile, File
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible


@deconstructible
class DatabaseStorage(Storage):
    """Stores file content in the database (StoredFile model)."""

    def _get_model(self):
        # Lazy import to avoid circular / AppRegistryNotReady errors
        from boards.models import StoredFile
        return StoredFile

    # ------------------------------------------------------------------
    # required interface
    # ------------------------------------------------------------------

    def _save(self, name: str, content: File) -> str:
        """Save file content to the database. Returns the storage key (UUID hex)."""
        StoredFile = self._get_model()

        data = content.read()
        checksum = hashlib.sha256(data).hexdigest()

        # Deduplication: if identical content already exists, reuse it
        existing = StoredFile.objects.filter(checksum=checksum).first()
        if existing:
            return str(existing.id)

        content_type = getattr(content, "content_type", None) or ""
        if not content_type:
            content_type = self._guess_content_type(name)

        # Nome sem extensão (gravador de tela salva "video-2026-08-01_12.03.56")
        # faz o navegador mandar application/octet-stream. Aí os bytes decidem —
        # senão o arquivo perde miniatura, player e conversão de vídeo.
        try:
            from boards.services.file_sniff import resolve_content_type
            content_type = resolve_content_type(content_type, data)
        except Exception:
            pass

        obj = StoredFile(
            original_name=name.split("/")[-1] if "/" in name else name,
            content_type=content_type,
            data=data,
            size=len(data),
            checksum=checksum,
        )
        obj.save()
        return str(obj.id)

    def _open(self, name: str, mode="rb") -> File:
        """Retrieve file content from the database."""
        StoredFile = self._get_model()
        obj = StoredFile.objects.get(id=name)
        return ContentFile(obj.data, name=obj.original_name)

    def exists(self, name: str) -> bool:
        if not name:
            return False
        StoredFile = self._get_model()
        try:
            return StoredFile.objects.filter(id=name).exists()
        except Exception:
            return False

    def delete(self, name: str):
        StoredFile = self._get_model()
        try:
            StoredFile.objects.filter(id=name).delete()
        except Exception:
            pass

    def url(self, name: str) -> str:
        """Return the URL where this file can be served."""
        return f"/media/serve/{name}/"

    def size(self, name: str) -> int:
        StoredFile = self._get_model()
        obj = StoredFile.objects.get(id=name)
        return obj.size

    def listdir(self, path: str):
        return [], []

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _guess_content_type(name: str) -> str:
        import mimetypes
        ct, _ = mimetypes.guess_type(name)
        return ct or "application/octet-stream"
