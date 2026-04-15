# boards/views/media_serve.py
"""
Views publicas para servir arquivos que podem estar no banco (StoredFile)
ou ainda em caminhos legados do filesystem.
"""

import mimetypes
import os
import unicodedata
import uuid

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.http import FileResponse, Http404
from django.utils._os import safe_join
from django.views.decorators.http import require_GET

from boards.models import StoredFile


INLINE_CONTENT_PREFIXES = ("image/", "video/", "audio/", "application/pdf")


def _content_disposition(content_type: str, original_name: str) -> str:
    disposition = "inline"
    if content_type and not content_type.startswith(INLINE_CONTENT_PREFIXES):
        disposition = "attachment"

    safe_name = (original_name or "file").replace('"', '\\"')
    return f'{disposition}; filename="{safe_name}"'


def _stored_file_response(stored: StoredFile) -> FileResponse:
    response = FileResponse(
        streaming_content=iter([bytes(stored.data)]),
        content_type=stored.content_type,
    )
    response["Content-Disposition"] = _content_disposition(
        stored.content_type or "application/octet-stream",
        stored.original_name,
    )
    response["Content-Length"] = stored.size
    response["Cache-Control"] = "public, max-age=604800, immutable"
    response["ETag"] = f'"{stored.checksum}"'
    return response


def _filesystem_file_response(file_path: str, file_ref: str) -> FileResponse:
    content_type = mimetypes.guess_type(file_ref)[0] or "application/octet-stream"
    response = FileResponse(open(file_path, "rb"), content_type=content_type)
    response["Content-Disposition"] = _content_disposition(content_type, os.path.basename(file_ref))
    response["Content-Length"] = os.path.getsize(file_path)
    response["Cache-Control"] = "public, max-age=604800"
    return response


def _lookup_stored_file(file_ref: str) -> StoredFile | None:
    try:
        file_uuid = uuid.UUID(str(file_ref))
    except (TypeError, ValueError, AttributeError):
        file_uuid = None

    if file_uuid:
        return StoredFile.objects.filter(id=file_uuid).first()

    basename = os.path.basename(file_ref or "")
    if not basename:
        return None

    candidates = {basename}
    for form in ("NFC", "NFD", "NFKC", "NFKD"):
        candidates.add(unicodedata.normalize(form, basename))

    matches = list(StoredFile.objects.filter(original_name__in=list(candidates))[:2])
    if len(matches) == 1:
        return matches[0]
    return None


def _safe_legacy_path(file_ref: str) -> str:
    try:
        return safe_join(settings.MEDIA_ROOT, file_ref)
    except SuspiciousFileOperation as exc:
        raise Http404("Caminho de arquivo invalido") from exc


@require_GET
def serve_stored_file(request, file_ref):
    """
    GET /media/serve/<uuid-ou-caminho-legado>/

    Ordem de resolucao:
    1. UUID valido em StoredFile.
    2. Caminho legado cujo basename tenha correspondencia unica em StoredFile.
    3. Fallback para arquivo legado ainda presente no filesystem.
    """
    stored = _lookup_stored_file(file_ref)
    if stored:
        return _stored_file_response(stored)

    for variant in _path_variants(file_ref):
        legacy_path = _safe_legacy_path(variant)
        if os.path.isfile(legacy_path):
            return _filesystem_file_response(legacy_path, variant)

    raise Http404("Arquivo nao encontrado")


def _path_variants(file_ref: str):
    if not file_ref:
        return []
    seen = []
    for form in ("original", "NFC", "NFD", "NFKC", "NFKD"):
        value = file_ref if form == "original" else unicodedata.normalize(form, file_ref)
        if value not in seen:
            seen.append(value)
    return seen
