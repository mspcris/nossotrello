"""Miniatura (PNG da 1ª página) de PDFs anexados — funciona em qualquer navegador.

A miniatura é guardada como um StoredFile comum, marcado via
`original_name = "pdfthumb::<source_uuid>.png"`. Assim NÃO precisa de migração
nem de modelo novo: o vínculo PDF→thumb é só uma convenção de nome.

Lookup é memoizado no cache (Redis) por source_id, pra não varrer a tabela de
StoredFile (original_name não é indexado) a cada render do feed.
"""

import hashlib
import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

_THUMB_PREFIX = "pdfthumb::"
_THUMB_MAX_PX = 600
_CACHE_TTL_OK = 7 * 24 * 3600      # thumb existe: memoiza por 7 dias
_CACHE_TTL_NONE = 3600             # falha/não-PDF: negativa curta (1h)


def _thumb_name(source_id) -> str:
    return f"{_THUMB_PREFIX}{source_id}.png"


def _cache_key(source_id) -> str:
    return f"pdfthumb:{source_id}"


def _render_first_page_png(pdf_bytes: bytes, max_px: int = _THUMB_MAX_PX):
    """Renderiza a 1ª página do PDF em PNG. Retorna bytes ou None."""
    try:
        import fitz  # PyMuPDF
    except Exception:
        logger.warning("PyMuPDF (fitz) indisponível; sem miniatura de PDF.")
        return None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            if doc.page_count < 1:
                return None
            page = doc.load_page(0)
            rect = page.rect
            big = max(rect.width, rect.height) or 1.0
            zoom = min(max_px / big, 4.0)
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            return pix.tobytes("png")
        finally:
            doc.close()
    except Exception:
        logger.exception("Falha ao renderizar miniatura de PDF.")
        return None


def get_or_create_pdf_thumb(source):
    """source = StoredFile do PDF (com .data). Retorna o StoredFile da miniatura ou None."""
    from boards.models import StoredFile

    if source is None:
        return None
    is_pdf = (source.content_type or "").lower() == "application/pdf" or \
             (source.original_name or "").lower().endswith(".pdf")
    if not is_pdf:
        return None

    name = _thumb_name(source.id)
    existing = StoredFile.objects.filter(original_name=name).only("id").first()
    if existing:
        return existing

    png = _render_first_page_png(bytes(source.data))
    if not png:
        return None

    return StoredFile.objects.create(
        original_name=name,
        content_type="image/png",
        data=png,
        size=len(png),
        checksum=hashlib.sha256(png).hexdigest(),
    )


def thumb_url_for_source_id(source_id) -> str:
    """URL /media/serve/ da miniatura do PDF cujo StoredFile.id == source_id.

    Memoiza no cache. Gera sob demanda na primeira vez (cobre PDFs já existentes).
    Retorna "" se não houver miniatura (não-PDF, PDF inválido, ou fitz ausente).
    """
    from boards.models import StoredFile

    ck = _cache_key(source_id)
    cached = cache.get(ck)
    if cached is not None:
        return f"/media/serve/{cached}/" if cached and cached != "none" else ""

    # 1) já existe?
    name = _thumb_name(source_id)
    thumb = StoredFile.objects.filter(original_name=name).only("id").first()
    if thumb:
        cache.set(ck, str(thumb.id), _CACHE_TTL_OK)
        return f"/media/serve/{thumb.id}/"

    # 2) gera (carrega o PDF inteiro só agora)
    source = StoredFile.objects.filter(id=source_id).first()
    thumb = get_or_create_pdf_thumb(source)
    if thumb:
        cache.set(ck, str(thumb.id), _CACHE_TTL_OK)
        return f"/media/serve/{thumb.id}/"

    cache.set(ck, "none", _CACHE_TTL_NONE)
    return ""


def ensure_thumb_for_fieldfile(fieldfile) -> None:
    """Best-effort: gera a miniatura no upload, pra o 1º render do feed já ser rápido."""
    try:
        import uuid as _uuid
        name = getattr(fieldfile, "name", "") or ""
        if not name:
            return
        key = name.split("/")[-1]
        thumb_url_for_source_id(_uuid.UUID(key))
    except Exception:
        pass
