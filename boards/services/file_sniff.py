"""Descobre o tipo real de um arquivo pelos primeiros bytes.

Por que existe: gravador de tela e apps de captura salvam com nome tipo
`video-2026-08-01_12.03.56` — sem extensão nenhuma. O navegador não tem como
adivinhar e manda `application/octet-stream`; o `file_meta` então classifica
como "arquivo comum" e o vídeo perde miniatura, player e conversão.

Os bytes não mentem: todo container tem assinatura no início. Aqui a gente lê
só o cabeçalho e devolve o content-type de verdade.

Escopo: os formatos que aparecem em anexo de card. O que não bater volta "" e o
chamador mantém o que já tinha.
"""

_HEAD_BYTES = 4096

# ftyp brands -> content type. O brand fica nos bytes 8..12 de MP4/MOV/HEIC.
_FTYP_EXACT = {
    b"qt  ": "video/quicktime",
    b"avif": "image/avif",
    b"avis": "image/avif",
    b"heic": "image/heic",
    b"heix": "image/heic",
    b"hevc": "image/heic",
    b"hevx": "image/heic",
    b"mif1": "image/heic",
    b"msf1": "image/heic",
}


def _sniff_ftyp(head: bytes) -> str:
    brand = head[8:12]
    if brand in _FTYP_EXACT:
        return _FTYP_EXACT[brand]
    if brand[:2] == b"3g":
        return "video/3gpp"
    # isom, mp41, mp42, avc1, iso2, M4V , mmp4, dash… tudo toca como MP4
    return "video/mp4"


def _sniff_ebml(head: bytes) -> str:
    # Matroska e WebM compartilham o header EBML; o DocType diferencia e fica
    # logo nos primeiros bytes.
    return "video/webm" if b"webm" in head[:64] else "video/x-matroska"


def _sniff_riff(head: bytes) -> str:
    fourcc = head[8:12]
    if fourcc == b"AVI ":
        return "video/x-msvideo"
    if fourcc == b"WEBP":
        return "image/webp"
    if fourcc == b"WAVE":
        return "audio/wav"
    return ""


def _sniff_ogg(head: bytes) -> str:
    if b"theora" in head or b"VP80" in head or b"VP90" in head:
        return "video/ogg"
    return "audio/ogg"


def sniff_content_type(data: bytes) -> str:
    """Content-type inferido pelo cabeçalho, ou "" se não reconhecer."""
    if not data:
        return ""

    head = bytes(data[:_HEAD_BYTES])
    if len(head) < 12:
        return ""

    # --- vídeo ---
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return _sniff_ebml(head)
    if head[4:8] == b"ftyp":
        return _sniff_ftyp(head)
    if head[:4] == b"RIFF":
        return _sniff_riff(head)
    if head[:4] == b"OggS":
        return _sniff_ogg(head)
    if head[:4] == b"FLV\x01":
        return "video/x-flv"
    if head[:4] == b"\x30\x26\xb2\x75":
        return "video/x-ms-asf"
    if head[:4] in (b"\x00\x00\x01\xba", b"\x00\x00\x01\xb3"):
        return "video/mpeg"

    # --- imagem / documento ---
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"%PDF":
        return "application/pdf"
    if head[:2] == b"BM":
        return "image/bmp"

    return ""


# Tipos que na prática significam "o navegador não soube dizer" — só nesses a
# gente confia mais nos bytes do que no que veio declarado.
_WEAK_TYPES = {
    "",
    "application/octet-stream",
    "binary/octet-stream",
    "application/unknown",
    "text/plain",
}


def resolve_content_type(declared: str, data: bytes) -> str:
    """Content-type final: mantém o declarado, salvo quando ele não diz nada."""
    declared = (declared or "").strip()
    if declared.lower().split(";")[0].strip() not in _WEAK_TYPES:
        return declared

    return sniff_content_type(data) or declared
