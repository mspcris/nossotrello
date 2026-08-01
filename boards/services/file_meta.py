"""Metadados de exibição de um arquivo anexado: nome real, extensão e tipo.

Os arquivos vivem no `DatabaseStorage`, então o `name` do FileField é a chave
UUID do StoredFile e a URL não tem extensão (`/media/serve/<uuid>/`). O nome que
o usuário escolheu/arrastou só existe em `StoredFile.original_name` — sem passar
por aqui, a interface mostra o UUID e ninguém reconhece o próprio arquivo.

Lookup memoizado no cache: linhas de StoredFile são imutáveis (conteúdo e nome
nunca mudam depois do save), então cachear por UUID é seguro.
"""

import mimetypes
import uuid as _uuid

from django.core.cache import cache

_CACHE_TTL = 7 * 24 * 3600

_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".avif", ".heic")
_VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".3gp")

# Sem StoredFile (linha apagada ou chave órfã) não dá pra recuperar o nome —
# melhor um rótulo genérico do que despejar o UUID na tela.
_FALLBACK_NAME = "arquivo"


def _raw_name(fieldfile) -> str:
    """`name` de um FieldFile, de uma string crua, ou "" se não der."""
    if isinstance(fieldfile, str):
        return fieldfile
    try:
        return getattr(fieldfile, "name", "") or ""
    except Exception:
        return ""


def _stored_row(key: str):
    """(original_name, content_type, is_uuid) do StoredFile de chave `key`."""
    try:
        uid = _uuid.UUID(key)
    except (ValueError, TypeError, AttributeError):
        return "", "", False

    ck = f"sfmeta:{uid}"
    try:
        cached = cache.get(ck)
    except Exception:
        cached = None

    if cached is None:
        from boards.models import StoredFile

        try:
            sf = (
                StoredFile.objects
                .filter(id=uid)
                .only("original_name", "content_type")
                .first()
            )
        except Exception:
            return "", "", True

        cached = {
            "name": (sf.original_name or "") if sf else "",
            "ct": (sf.content_type or "") if sf else "",
        }
        try:
            cache.set(ck, cached, _CACHE_TTL)
        except Exception:
            pass

    return cached.get("name", ""), cached.get("ct", ""), True


def file_meta(fieldfile) -> dict:
    """`{"name", "ext", "kind", "missing"}` — 1 query memoizada por StoredFile.

    - `name`: nome original ("relatorio.pdf"), nunca o UUID de storage.
    - `ext`:  extensão em maiúsculas sem ponto ("PDF"), "" se indeterminada.
    - `kind`: "image" | "pdf" | "video" | "file" — decide se dá pra pré-visualizar.
    - `missing`: os bytes sumiram (chave órfã). O template mostra "arquivo
      indisponível" em vez de um link que devolve 404.
    """
    raw = _raw_name(fieldfile)
    if not raw:
        return {"name": "", "ext": "", "kind": "file", "missing": False}

    key = raw.split("/")[-1]
    orig, ct, is_uuid = _stored_row(key)
    ct = (ct or "").lower()

    # Chave em formato UUID sem linha correspondente = blob que não existe mais.
    # Referência legada (caminho) não passa por aqui e continua indo pro
    # fallback do media_serve.
    missing = bool(is_uuid and not orig and not ct)

    # Caminho legado ("attachments/foo.pdf") já traz o nome no próprio path.
    name = orig or (_FALLBACK_NAME if is_uuid else key)

    ext = ""
    if "." in name:
        cand = name.rsplit(".", 1)[-1]
        # `any(isalpha)`: "video-2026-08-01_12.03.56" não tem extensão nenhuma —
        # o "56" é o segundo do horário. Sem essa checagem o anexo virava um
        # arquivo ".56" e perdia o tratamento de vídeo.
        if 1 <= len(cand) <= 5 and cand.isalnum() and any(c.isalpha() for c in cand):
            ext = cand.upper()
    if not ext and ct:
        guess = mimetypes.guess_extension(ct.split(";")[0].strip()) or ""
        ext = guess.lstrip(".").upper()

    lower = name.lower()
    if ct.startswith("image/") or lower.endswith(_IMAGE_EXTS):
        kind = "image"
    elif ct == "application/pdf" or lower.endswith(".pdf"):
        kind = "pdf"
    elif ct.startswith("video/") or lower.endswith(_VIDEO_EXTS):
        kind = "video"
    else:
        kind = "file"

    return {"name": name, "ext": ext, "kind": kind, "missing": missing}


def display_name(fieldfile) -> str:
    """Nome real do arquivo pra mostrar/logar (nunca o UUID)."""
    return file_meta(fieldfile)["name"]
