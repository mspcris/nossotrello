"""Compressão de imagens no upload.

Reduz peso/dimensão das fotos antes de salvar pra carregar mais rápido em
redes lentas, sem mexer no front. Preserva orientação EXIF (iPhone/Android
gravam a foto girada + tag de orientação — se ignorarmos, a foto aparece
deitada).

GIF e WebP animado passam direto (re-encodar mataria a animação). Imagens
muito pequenas também — já estão leves, comprimir de novo só adiciona
artefatos.
"""

from __future__ import annotations

import io
import logging
import mimetypes
import os

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile

try:
    from PIL import Image, ImageOps, UnidentifiedImageError
except ImportError:  # pragma: no cover
    Image = None  # type: ignore
    ImageOps = None  # type: ignore
    UnidentifiedImageError = Exception  # type: ignore

_log = logging.getLogger(__name__)

# Formatos que NÃO queremos recomprimir (animação/transparência importante)
_PASSTHROUGH_EXT = {".gif", ".webp", ".avif", ".svg"}
_PASSTHROUGH_CT = {"image/gif", "image/webp", "image/avif", "image/svg+xml"}

DEFAULT_MAX_WIDTH = 1600      # redimensiona se largura > isso
DEFAULT_QUALITY = 85          # qualidade JPEG (85 = sweet spot)
MIN_BYTES_TO_COMPRESS = 150 * 1024  # < 150KB: já tá leve, deixa como veio


def compress_image(
    f,
    *,
    max_width: int = DEFAULT_MAX_WIDTH,
    quality: int = DEFAULT_QUALITY,
    force_jpeg: bool = True,
):
    """Retorna um arquivo (UploadedFile ou ContentFile) comprimido ou o
    próprio `f` quando não vale a pena processar.

    - Passa direto: GIF, WebP, AVIF, SVG, arquivos pequenos, tipos não-imagem.
    - Caso contrário: abre com PIL, aplica rotação EXIF, redimensiona se
      largura > max_width, salva como JPEG quality 85. Nome do arquivo
      recebe sufixo ".jpg".

    Em qualquer erro, loga e devolve o arquivo original — nunca deixa o
    upload cair por causa da compressão.
    """
    if Image is None:
        return f  # Pillow indisponível — fallback silencioso

    if f is None:
        return f

    name = (getattr(f, "name", "") or "").lower()
    ext = os.path.splitext(name)[1]
    ct = (getattr(f, "content_type", "") or "").lower()

    # Passa direto: GIF/WebP/AVIF/SVG (animação/vetor)
    if ext in _PASSTHROUGH_EXT or ct in _PASSTHROUGH_CT:
        return f

    # Tipo não-imagem — fallback por segurança
    if ct and not ct.startswith("image/"):
        # Se content_type não é imagem, talvez o cliente mandou sem tipo;
        # ainda tenta abrir via Pillow abaixo.
        pass

    size = getattr(f, "size", 0) or 0
    if size and size < MIN_BYTES_TO_COMPRESS:
        return f  # já tá pequeno

    try:
        f.seek(0)
        with Image.open(f) as img:
            # Respeita rotação EXIF (iPhone/Android)
            img = ImageOps.exif_transpose(img)

            # Formato animado detectado após abrir (paranoia extra)
            if getattr(img, "is_animated", False):
                f.seek(0)
                return f

            # Flatten RGBA em fundo branco quando vamos salvar JPEG
            if force_jpeg and img.mode not in ("RGB", "L"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                if "A" in img.mode:
                    bg.paste(img, mask=img.split()[-1])
                else:
                    bg.paste(img)
                img = bg

            # Redimensiona preservando aspect ratio
            if img.width > max_width:
                ratio = max_width / float(img.width)
                new_size = (max_width, int(round(img.height * ratio)))
                img = img.resize(new_size, Image.LANCZOS)

            buf = io.BytesIO()
            fmt = "JPEG" if force_jpeg else (img.format or "JPEG")
            save_kwargs = {"format": fmt, "optimize": True}
            if fmt == "JPEG":
                save_kwargs["quality"] = quality
                save_kwargs["progressive"] = True
            img.save(buf, **save_kwargs)
            buf.seek(0)

        # Se o resultado ficou MAIOR que o original (imagem já comprimida
        # ou muito pequena), devolve o original.
        new_size = buf.getbuffer().nbytes
        if size and new_size >= size:
            f.seek(0)
            return f

        # Monta nome final com extensão correta
        base, _ = os.path.splitext(os.path.basename(name or "upload"))
        out_name = f"{base}.jpg" if fmt == "JPEG" else (name or "upload")

        out = ContentFile(buf.getvalue(), name=out_name)
        _log.debug(
            "compress_image: %s %d → %d bytes (%.0f%%)",
            name, size, new_size, (new_size / size * 100) if size else 0,
        )
        return out

    except (UnidentifiedImageError, OSError, ValueError) as exc:
        _log.warning("compress_image: falha em %s (%s) — devolvendo original", name, exc)
        try:
            f.seek(0)
        except Exception:
            pass
        return f
