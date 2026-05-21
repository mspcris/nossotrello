"""Transcodificação de vídeo via ffmpeg + extração de poster image.

Usado em background depois do upload de vídeo (social_post_create).
Objetivo:
  - moov atom no início (faststart) → player começa a tocar com os
    primeiros KB
  - máx 720p de resolução
  - bitrate alvo ~1Mbps → vídeo de 60s sai com ~7-8MB (vs 17MB original)
  - H.264 baseline + AAC pra compatibilidade máxima
  - poster image extraída do 1º frame (segundo 0.5) pra <video poster=...>

Tudo best-effort: se ffmpeg falhar ou não estiver no PATH, o pipeline
loga em warning e termina sem propagar — o post fica com o vídeo original.
"""

import logging
import os
import shutil
import subprocess
import tempfile
import threading

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction


logger = logging.getLogger(__name__)


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _compress_to_files(src_path: str, dst_path: str, poster_path: str) -> bool:
    """Roda ffmpeg pra transcodificar `src_path` em `dst_path` e gerar
    `poster_path`. Retorna True se ambos saíram OK."""

    # Transcode principal
    transcode_cmd = [
        "ffmpeg", "-y",
        "-i", src_path,
        # Vídeo: H.264 baseline, max 720p mantendo aspect, ~1Mbps, 30fps
        "-c:v", "libx264",
        "-profile:v", "baseline",
        "-level", "3.1",
        "-pix_fmt", "yuv420p",
        "-vf", "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease",
        "-b:v", "1000k",
        "-maxrate", "1500k",
        "-bufsize", "2000k",
        "-r", "30",
        # Áudio: AAC 96kbps, mono se a fonte for mono, stereo senão
        "-c:a", "aac",
        "-b:a", "96k",
        # Container: MP4 com moov no início (faststart)
        "-movflags", "+faststart",
        "-f", "mp4",
        dst_path,
    ]
    try:
        r = subprocess.run(transcode_cmd, capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        logger.warning("video_compress: ffmpeg transcode timeout em %s", src_path)
        return False
    if r.returncode != 0:
        logger.warning(
            "video_compress: ffmpeg transcode falhou (rc=%s): %s",
            r.returncode,
            r.stderr.decode("utf-8", errors="replace")[:500],
        )
        return False

    # Poster: frame em 0.5s, escalado, JPEG quality decente
    poster_cmd = [
        "ffmpeg", "-y",
        "-ss", "0.5",
        "-i", src_path,
        "-frames:v", "1",
        "-vf", "scale='min(720,iw)':'min(720,ih)':force_original_aspect_ratio=decrease",
        "-q:v", "4",
        poster_path,
    ]
    try:
        r = subprocess.run(poster_cmd, capture_output=True, timeout=30)
    except subprocess.TimeoutExpired:
        logger.warning("video_compress: ffmpeg poster timeout em %s", src_path)
        # Vídeo OK ainda assim — poster é opcional
        return True
    if r.returncode != 0:
        logger.warning(
            "video_compress: ffmpeg poster falhou (rc=%s): %s",
            r.returncode,
            r.stderr.decode("utf-8", errors="replace")[:300],
        )
        # Vídeo OK; só fica sem poster

    return True


def _process_post_sync(post_id: int):
    """Pipeline sincrono: lê o vídeo do StoredFile, transcodifica, e
    substitui post.video + grava post.video_poster."""
    if not _has_ffmpeg():
        logger.info("video_compress: ffmpeg ausente, pulando post_id=%s", post_id)
        return

    from boards.models import SocialPost

    try:
        post = SocialPost.objects.select_related("user").get(id=post_id, is_active=True)
    except SocialPost.DoesNotExist:
        return

    if not post.video:
        return
    if post.video_poster:
        # Já processado
        return

    # Lê os bytes do vídeo original (pode estar no DatabaseStorage ou FS)
    try:
        with post.video.open("rb") as f:
            original_bytes = f.read()
    except Exception as exc:
        logger.warning("video_compress: falha lendo vídeo do post_id=%s: %s", post_id, exc)
        return

    if not original_bytes:
        return

    with tempfile.TemporaryDirectory(prefix="vcompress_") as tmp:
        src = os.path.join(tmp, "src.bin")
        dst = os.path.join(tmp, "compressed.mp4")
        poster = os.path.join(tmp, "poster.jpg")
        with open(src, "wb") as f:
            f.write(original_bytes)

        ok = _compress_to_files(src, dst, poster)
        if not ok:
            return

        # Lê resultados
        if not os.path.exists(dst):
            return
        with open(dst, "rb") as f:
            new_video_bytes = f.read()
        if not new_video_bytes:
            return

        new_poster_bytes = b""
        if os.path.exists(poster):
            with open(poster, "rb") as f:
                new_poster_bytes = f.read()

    old_video_name = post.video.name
    old_video_storage = post.video.storage

    # Anexa o vídeo comprimido
    post.video.save(
        f"video_{post.id}.mp4",
        SimpleUploadedFile(
            name=f"video_{post.id}.mp4",
            content=new_video_bytes,
            content_type="video/mp4",
        ),
        save=False,
    )

    # Anexa o poster (se gerado)
    if new_poster_bytes:
        post.video_poster.save(
            f"poster_{post.id}.jpg",
            SimpleUploadedFile(
                name=f"poster_{post.id}.jpg",
                content=new_poster_bytes,
                content_type="image/jpeg",
            ),
            save=False,
        )

    post.save(update_fields=["video", "video_poster"])

    # Limpa o arquivo antigo (StoredFile UUID órfão)
    if old_video_name and old_video_name != post.video.name:
        try:
            old_video_storage.delete(old_video_name)
        except Exception as exc:
            logger.warning("video_compress: falha removendo storage antigo %s: %s", old_video_name, exc)

    new_size_mb = len(new_video_bytes) / (1024 * 1024)
    orig_size_mb = len(original_bytes) / (1024 * 1024)
    logger.info(
        "video_compress: post_id=%s %.1fMB → %.1fMB (%.0f%%) poster=%s",
        post_id, orig_size_mb, new_size_mb,
        (new_size_mb / orig_size_mb * 100) if orig_size_mb else 0,
        bool(new_poster_bytes),
    )


def schedule_video_compress(post_id: int):
    """Agenda transcodificação em background depois do COMMIT."""
    if not _is_enabled():
        return

    def _runner():
        try:
            _process_post_sync(post_id)
        except Exception:
            logger.exception("video_compress: erro processando post_id=%s", post_id)

    def _spawn():
        t = threading.Thread(target=_runner, name=f"video-compress-{post_id}", daemon=True)
        t.start()

    try:
        transaction.on_commit(_spawn)
    except Exception:
        _spawn()


def _is_enabled() -> bool:
    """Kill switch via env var. VIDEO_COMPRESS_ENABLED=0 desliga."""
    return os.getenv("VIDEO_COMPRESS_ENABLED", "1") != "0"
