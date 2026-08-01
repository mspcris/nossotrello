"""Cópia normalizada (H.264/AAC/faststart) de um vídeo anexado.

Por que existe: o que o usuário arrasta pro card é o que a câmera dele gerou —
HEVC de iPhone, VP9 num .webm, MPEG-4 Part 2 num .avi antigo. O `<video>` do
navegador só toca o que ele sabe decodificar; no resto ele fica preto ou nem
carrega, e o clique acabava virando download.

A solução é a mesma convenção do `video_thumbs`: a cópia tocável é um
StoredFile comum marcado por `original_name = "vidplay::<source_uuid>.mp4"`.
Sem migração, sem modelo novo — o vínculo original→tocável é o nome.

O ORIGINAL NUNCA É APAGADO. Diferente do `video_compress` dos posts (que troca
o arquivo do post), aqui o blob é deduplicado por checksum e pode estar
apontado por outros cards e por CardLog antigos — trocar/remover quebraria o
histórico. A cópia vive ao lado; o player usa ela quando existe.

Tudo best-effort e em background: sem ffmpeg, ou com vídeo que ele não
decodifica, o player cai no arquivo original e, se nem esse tocar, mostra o
aviso com o link de baixar.
"""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import uuid as _uuid

from django.core.cache import cache
from django.db import transaction

logger = logging.getLogger(__name__)

_PLAY_PREFIX = "vidplay::"

_CACHE_TTL_OK = 7 * 24 * 3600     # cópia existe (ou dispensável): 7 dias
_CACHE_TTL_NONE = 600             # ainda não existe: negativa curta (10 min)
_INFLIGHT_TTL = 30 * 60           # trava anti-duplicata de transcode

# Dois marcadores diferentes de propósito: "none" é "ainda não tem, tenta de
# novo"; "skip" é "o original já toca em qualquer navegador, não precisa cópia".
# Sem essa distinção, a negativa curta fazia o ensure() pular o agendamento.
_MARK_PENDING = "none"
_MARK_SKIP = "skip"

_FFPROBE_TIMEOUT = 20
_FFMPEG_TIMEOUT = 15 * 60         # vídeo de 50MB em 720p cabe folgado

# Combinação que qualquer navegador atual decodifica sem plugin nenhum.
_SAFE_VIDEO_CODECS = {"h264"}
_SAFE_AUDIO_CODECS = {"aac", "mp3"}


def _play_name(source_id) -> str:
    return f"{_PLAY_PREFIX}{source_id}.mp4"


def _cache_key(source_id) -> str:
    return f"vidplay:{source_id}"


def _inflight_key(source_id) -> str:
    return f"vidplay:working:{source_id}"


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def source_id_of(fieldfile):
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


def _probe_streams(path: str):
    """[(codec_type, codec_name), …] do arquivo, ou None se o ffprobe falhar."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_type,codec_name",
        "-of", "json",
        path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=_FFPROBE_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None

    try:
        data = json.loads(r.stdout.decode("utf-8", errors="replace") or "{}")
    except ValueError:
        return None

    out = []
    for s in (data.get("streams") or []):
        out.append(((s.get("codec_type") or "").lower(), (s.get("codec_name") or "").lower()))
    return out


def _already_playable(path: str, original_name: str) -> bool:
    """True quando o arquivo já é MP4 com H.264 (+ AAC/MP3 ou mudo).

    Vale a pena checar: a maioria dos vídeos de celular já chega assim, e
    transcodificar de novo só queimaria CPU e perderia qualidade.
    """
    if not (original_name or "").lower().endswith(".mp4"):
        return False

    streams = _probe_streams(path)
    if streams is None:
        return False

    saw_video = False
    for codec_type, codec_name in streams:
        if codec_type == "video":
            saw_video = True
            if codec_name not in _SAFE_VIDEO_CODECS:
                return False
        elif codec_type == "audio":
            if codec_name not in _SAFE_AUDIO_CODECS:
                return False

    return saw_video


def _transcode(src_path: str, dst_path: str) -> bool:
    """H.264 baseline + AAC em MP4 com moov no início. True se saiu arquivo."""
    cmd = [
        "ffmpeg", "-y",
        "-i", src_path,
        # Vídeo: baseline/3.1 + yuv420p = o denominador comum de tudo que toca
        "-c:v", "libx264",
        "-profile:v", "baseline",
        "-level", "3.1",
        "-pix_fmt", "yuv420p",
        "-preset", "veryfast",
        "-crf", "26",
        # Teto de 720p; vídeo menor que isso não é ampliado
        "-vf", "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease"
               ":force_divisible_by=2",
        # Áudio: AAC. Vídeo mudo passa reto — sem stream de áudio o ffmpeg
        # simplesmente ignora estas opções.
        "-c:a", "aac",
        "-b:a", "128k",
        "-ac", "2",
        # moov no início: o player começa a tocar sem baixar o arquivo inteiro
        "-movflags", "+faststart",
        "-f", "mp4",
        dst_path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=_FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired:
        logger.warning("video_playable: ffmpeg timeout em %s", src_path)
        return False
    except OSError as exc:
        logger.warning("video_playable: ffmpeg indisponível: %s", exc)
        return False

    if r.returncode != 0:
        logger.warning(
            "video_playable: ffmpeg falhou (rc=%s): %s",
            r.returncode,
            r.stderr.decode("utf-8", errors="replace")[:500],
        )
        return False

    return os.path.exists(dst_path) and os.path.getsize(dst_path) > 0


def _build_playable_sync(source_id) -> bool:
    """Gera (se precisar) a cópia tocável do StoredFile `source_id`."""
    from boards.models import StoredFile

    if not _has_ffmpeg():
        logger.info("video_playable: ffmpeg ausente, pulando %s", source_id)
        return False

    name = _play_name(source_id)
    if StoredFile.objects.filter(original_name=name).exists():
        return True

    source = StoredFile.objects.filter(id=source_id).first()
    if source is None or not source.data:
        return False

    orig_name = source.original_name or ""
    suffix = os.path.splitext(orig_name)[1] or ".mp4"

    tmpdir = tempfile.mkdtemp(prefix="vidplay-")
    try:
        src = os.path.join(tmpdir, f"src{suffix}")
        dst = os.path.join(tmpdir, "playable.mp4")

        with open(src, "wb") as f:
            f.write(bytes(source.data))

        if _already_playable(src, orig_name):
            # Nada a fazer: o player usa o próprio original. Marca a negativa
            # longa pra não reprocessar esse vídeo a cada render do feed.
            cache.set(_cache_key(source_id), _MARK_SKIP, _CACHE_TTL_OK)
            return True

        if not _transcode(src, dst):
            return False

        with open(dst, "rb") as f:
            payload = f.read()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    if not payload:
        return False

    # Corrida com outra thread que gerou a mesma cópia: quem chegar depois
    # reaproveita em vez de duplicar o blob.
    existing = StoredFile.objects.filter(original_name=name).only("id").first()
    if existing:
        cache.set(_cache_key(source_id), str(existing.id), _CACHE_TTL_OK)
        return True

    row = StoredFile.objects.create(
        original_name=name,
        content_type="video/mp4",
        data=payload,
        size=len(payload),
        checksum=hashlib.sha256(payload).hexdigest(),
    )
    cache.set(_cache_key(source_id), str(row.id), _CACHE_TTL_OK)

    logger.info(
        "video_playable: %s → %s (%.1fMB)",
        source_id, row.id, len(payload) / (1024 * 1024),
    )
    return True


def playable_url_for_source_id(source_id) -> str:
    """URL /media/serve/ da cópia tocável, ou "" se ainda não existe.

    Só consulta — nunca transcodifica aqui dentro. Render de feed não pode
    ficar preso esperando ffmpeg.
    """
    from boards.models import StoredFile

    ck = _cache_key(source_id)
    cached = cache.get(ck)
    if cached is not None:
        if not cached or cached in (_MARK_PENDING, _MARK_SKIP):
            return ""
        return f"/media/serve/{cached}/"

    row = (
        StoredFile.objects
        .filter(original_name=_play_name(source_id))
        .only("id")
        .first()
    )
    if row:
        cache.set(ck, str(row.id), _CACHE_TTL_OK)
        return f"/media/serve/{row.id}/"

    cache.set(ck, _MARK_PENDING, _CACHE_TTL_NONE)
    return ""


def schedule_playable(source_id) -> None:
    """Agenda a conversão em background, no máximo uma por vídeo em voo."""
    if source_id is None:
        return
    if os.getenv("VIDEO_PLAYABLE_ENABLED", "1") == "0":
        return

    lock = _inflight_key(source_id)
    try:
        # add() só grava se a chave não existir — é o lock entre threads/processos
        if not cache.add(lock, "1", _INFLIGHT_TTL):
            return
    except Exception:
        pass

    def _runner():
        try:
            _build_playable_sync(source_id)
        except Exception:
            logger.exception("video_playable: erro convertendo %s", source_id)
        finally:
            try:
                cache.delete(lock)
            except Exception:
                pass

    def _spawn():
        threading.Thread(
            target=_runner,
            name=f"video-playable-{source_id}",
            daemon=True,
        ).start()

    try:
        transaction.on_commit(_spawn)
    except Exception:
        _spawn()


def ensure_playable_for_fieldfile(fieldfile) -> None:
    """Best-effort: garante a cópia tocável de um anexo de vídeo."""
    try:
        from boards.services.file_meta import file_meta

        if (file_meta(fieldfile) or {}).get("kind") != "video":
            return

        uid = source_id_of(fieldfile)
        if uid is None:
            return

        # Já tem cópia, ou o original já foi checado e dispensa cópia.
        # A negativa curta (_MARK_PENDING) NÃO conta — ela só diz "ainda não
        # existe", que é exatamente o caso em que a gente quer agendar.
        cached = cache.get(_cache_key(uid))
        if cached is not None and cached != _MARK_PENDING:
            return

        schedule_playable(uid)
    except Exception:
        pass
