"""Miniatura de um anexo, seja qual for o tipo.

Despacha pro gerador certo pelo `kind` do arquivo (ver services/file_meta.py):

    pdf   -> 1ª página            (services/pdf_thumbs.py, PyMuPDF)
    video -> 1º frame             (services/video_thumbs.py, ffmpeg)
    resto -> "" (o template cai na folha genérica com a extensão)

Imagem não passa por aqui: a própria URL do arquivo já é a miniatura.
"""

import uuid as _uuid

from boards.services.file_meta import file_meta


def _source_id(fieldfile):
    """UUID do StoredFile de um anexo, ou None se for referência legada."""
    try:
        name = getattr(fieldfile, "name", "") or ""
    except Exception:
        return None
    if not name:
        return None
    try:
        return _uuid.UUID(name.split("/")[-1])
    except (ValueError, TypeError, AttributeError):
        return None


def thumb_url_for_fieldfile(fieldfile) -> str:
    """URL /media/serve/ da miniatura, ou "" quando não há como gerar."""
    uid = _source_id(fieldfile)
    if uid is None:
        return ""

    kind = file_meta(fieldfile)["kind"]

    try:
        if kind == "pdf":
            from boards.services.pdf_thumbs import thumb_url_for_source_id
            return thumb_url_for_source_id(uid) or ""
        if kind == "video":
            from boards.services.video_thumbs import thumb_url_for_source_id
            return thumb_url_for_source_id(uid) or ""
    except Exception:
        return ""

    return ""


def ensure_thumb_for_fieldfile(fieldfile) -> None:
    """Best-effort: gera a miniatura no upload, pra o 1º render do feed já ser rápido."""
    try:
        thumb_url_for_fieldfile(fieldfile)
    except Exception:
        pass
