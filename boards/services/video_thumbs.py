"""Miniatura (1º frame) de vídeos anexados — mesmo contrato do pdf_thumbs.

A miniatura é guardada como um StoredFile comum, marcado via
`original_name = "vidthumb::<source_uuid>.jpg"`. Assim NÃO precisa de migração
nem de modelo novo: o vínculo vídeo→thumb é só uma convenção de nome.

Lookup é memoizado no cache (Redis) por source_id, pra não varrer a tabela de
StoredFile (original_name não é indexado) a cada render do feed.

Tudo best-effort: sem ffmpeg no PATH, ou vídeo que o ffmpeg não decodifica, o
anexo cai na folha genérica com a extensão — nunca num quadrado vazio.
"""

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile

from django.core.cache import cache

logger = logging.getLogger(__name__)

_THUMB_PREFIX = "vidthumb::"
_THUMB_MAX_PX = 600
_CACHE_TTL_OK = 7 * 24 * 3600      # thumb existe: memoiza por 7 dias
_CACHE_TTL_NONE = 3600             # falha/não-vídeo: negativa curta (1h)

# Frame em 0.5s evita o fade-in preto que muitos vídeos têm no instante 0.
_SEEK_SECONDS = ("0.5", "0")
_FFMPEG_TIMEOUT = 30


def _thumb_name(source_id) -> str:
    return f"{_THUMB_PREFIX}{source_id}.jpg"


def _cache_key(source_id) -> str:
    return f"vidthumb:{source_id}"


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _extract_frame_jpeg(video_bytes: bytes, suffix: str = ".mp4"):
    """Extrai o 1º frame do vídeo em JPEG. Retorna bytes ou None."""
    if not _has_ffmpeg():
        logger.warning("ffmpeg indisponível; sem miniatura de vídeo.")
        return None

    tmpdir = tempfile.mkdtemp(prefix="vidthumb-")
    src = os.path.join(tmpdir, f"src{suffix}")
    dst = os.path.join(tmpdir, "frame.jpg")
    try:
        with open(src, "wb") as f:
            f.write(video_bytes)

        for seek in _SEEK_SECONDS:
            cmd = [
                "ffmpeg", "-y",
                # -ss ANTES do -i = seek rápido, não decodifica o vídeo inteiro
                "-ss", seek,
                "-i", src,
                "-frames:v", "1",
                "-vf",
                f"scale='min({_THUMB_MAX_PX},iw)':'min({_THUMB_MAX_PX},ih)'"
                ":force_original_aspect_ratio=decrease",
                "-q:v", "4",
                dst,
            ]
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=_FFMPEG_TIMEOUT)
            except subprocess.TimeoutExpired:
                logger.warning("video_thumbs: ffmpeg timeout (seek=%s)", seek)
                return None

            if r.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0:
                with open(dst, "rb") as f:
                    return f.read()

            # vídeo mais curto que o seek: tenta de novo a partir do frame 0
            logger.info(
                "video_thumbs: ffmpeg sem frame em seek=%s (rc=%s)", seek, r.returncode
            )

        return None
    except Exception:
        logger.exception("Falha ao extrair frame de vídeo.")
        return None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def get_or_create_video_thumb(source):
    """source = StoredFile do vídeo (com .data). Retorna o StoredFile da miniatura ou None."""
    from boards.models import StoredFile

    if source is None:
        return None

    is_video = (source.content_type or "").lower().startswith("video/") or \
        (source.original_name or "").lower().endswith(
            (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".3gp")
        )
    if not is_video:
        return None

    name = _thumb_name(source.id)
    existing = StoredFile.objects.filter(original_name=name).only("id").first()
    if existing:
        return existing

    orig = (source.original_name or "").lower()
    suffix = os.path.splitext(orig)[1] or ".mp4"
    jpeg = _extract_frame_jpeg(bytes(source.data), suffix=suffix)
    if not jpeg:
        return None

    return StoredFile.objects.create(
        original_name=name,
        content_type="image/jpeg",
        data=jpeg,
        size=len(jpeg),
        checksum=hashlib.sha256(jpeg).hexdigest(),
    )


def thumb_url_for_source_id(source_id) -> str:
    """URL /media/serve/ da miniatura do vídeo cujo StoredFile.id == source_id.

    Memoiza no cache. Gera sob demanda na primeira vez (cobre vídeos já
    existentes). Retorna "" se não houver miniatura.
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

    # 2) gera (carrega o vídeo inteiro só agora)
    source = StoredFile.objects.filter(id=source_id).first()
    thumb = get_or_create_video_thumb(source)
    if thumb:
        cache.set(ck, str(thumb.id), _CACHE_TTL_OK)
        return f"/media/serve/{thumb.id}/"

    cache.set(ck, "none", _CACHE_TTL_NONE)
    return ""
