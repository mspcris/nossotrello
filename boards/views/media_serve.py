# boards/views/media_serve.py
"""
View pública que serve arquivos armazenados no banco (StoredFile).
Substitui o Nginx `location /media/` para arquivos migrados.
"""

from django.http import FileResponse, Http404
from django.views.decorators.http import require_GET

from boards.models import StoredFile


@require_GET
def serve_stored_file(request, file_id):
    """
    GET /media/serve/<uuid>/
    Serve o binário direto do banco com headers de cache e content-type correto.
    Para arquivos grandes (>1MB) usa streaming automático via FileResponse.
    """
    try:
        stored = StoredFile.objects.get(id=file_id)
    except StoredFile.DoesNotExist:
        raise Http404("Arquivo não encontrado")

    response = FileResponse(
        streaming_content=iter([bytes(stored.data)]),
        content_type=stored.content_type,
    )

    # Content-Disposition: inline para mídia, attachment para o resto
    disposition = "inline"
    if stored.content_type and not stored.content_type.startswith(("image/", "video/", "audio/", "application/pdf")):
        disposition = "attachment"

    safe_name = stored.original_name.replace('"', '\\"') if stored.original_name else "file"
    response["Content-Disposition"] = f'{disposition}; filename="{safe_name}"'
    response["Content-Length"] = stored.size

    # Cache: 7 dias (mesmo que o Nginx fazia), ETag pelo checksum
    response["Cache-Control"] = "public, max-age=604800, immutable"
    response["ETag"] = f'"{stored.checksum}"'

    return response
