# boards/views/media_serve.py
"""
Views publicas para servir arquivos que podem estar no banco (StoredFile)
ou ainda em caminhos legados do filesystem.

Suporta HTTP Range Requests (RFC 7233) — sem isso, o <video> tag espera o
arquivo inteiro chegar antes de começar a tocar (vídeo de 17MB engasga em
'Carregando 0%' por dezenas de segundos).
"""

import mimetypes
import os
import re
import unicodedata
import uuid

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.utils._os import safe_join
from django.views.decorators.http import require_GET

from boards.models import StoredFile


INLINE_CONTENT_PREFIXES = ("image/", "video/", "audio/", "application/pdf")
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _content_disposition(content_type: str, original_name: str) -> str:
    disposition = "inline"
    if content_type and not content_type.startswith(INLINE_CONTENT_PREFIXES):
        disposition = "attachment"

    safe_name = (original_name or "file").replace('"', '\\"')
    return f'{disposition}; filename="{safe_name}"'


def _parse_range(header: str, total: int):
    """Parseia 'bytes=START-END' e retorna (start, end) clipped ao tamanho.
    Retorna None se inválido ou ausente. END é inclusivo, como no HTTP."""
    if not header or total <= 0:
        return None
    m = _RANGE_RE.match(header.strip())
    if not m:
        return None
    start_s, end_s = m.group(1), m.group(2)
    if start_s == "" and end_s == "":
        return None
    if start_s == "":
        # 'bytes=-N' → últimos N bytes
        try:
            n = int(end_s)
        except ValueError:
            return None
        if n <= 0:
            return None
        start = max(0, total - n)
        end = total - 1
    else:
        try:
            start = int(start_s)
        except ValueError:
            return None
        if start >= total:
            return None
        if end_s == "":
            end = total - 1
        else:
            try:
                end = int(end_s)
            except ValueError:
                return None
            end = min(end, total - 1)
        if end < start:
            return None
    return start, end


def _stored_file_response(stored: StoredFile, request) -> HttpResponse:
    total = stored.size
    content_type = stored.content_type or "application/octet-stream"
    data = bytes(stored.data)

    range_header = request.META.get("HTTP_RANGE", "")
    parsed = _parse_range(range_header, total)

    if parsed is not None:
        start, end = parsed
        length = end - start + 1
        response = HttpResponse(
            data[start:end + 1],
            status=206,
            content_type=content_type,
        )
        response["Content-Range"] = f"bytes {start}-{end}/{total}"
        response["Content-Length"] = str(length)
    else:
        response = HttpResponse(data, content_type=content_type)
        response["Content-Length"] = str(total)

    response["Accept-Ranges"] = "bytes"
    response["Content-Disposition"] = _content_disposition(content_type, stored.original_name)
    response["Cache-Control"] = "public, max-age=604800, immutable"
    response["ETag"] = f'"{stored.checksum}"'
    return response


def _filesystem_file_response(file_path: str, file_ref: str, request) -> HttpResponse:
    content_type = mimetypes.guess_type(file_ref)[0] or "application/octet-stream"
    total = os.path.getsize(file_path)

    range_header = request.META.get("HTTP_RANGE", "")
    parsed = _parse_range(range_header, total)

    if parsed is not None:
        start, end = parsed
        length = end - start + 1

        def _chunks():
            CHUNK = 64 * 1024
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    buf = f.read(min(CHUNK, remaining))
                    if not buf:
                        break
                    remaining -= len(buf)
                    yield buf

        response = StreamingHttpResponse(_chunks(), status=206, content_type=content_type)
        response["Content-Range"] = f"bytes {start}-{end}/{total}"
        response["Content-Length"] = str(length)
    else:
        response = FileResponse(open(file_path, "rb"), content_type=content_type)
        response["Content-Length"] = str(total)

    response["Accept-Ranges"] = "bytes"
    response["Content-Disposition"] = _content_disposition(content_type, os.path.basename(file_ref))
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
        return _stored_file_response(stored, request)

    for variant in _path_variants(file_ref):
        legacy_path = _safe_legacy_path(variant)
        if os.path.isfile(legacy_path):
            return _filesystem_file_response(legacy_path, variant, request)

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
