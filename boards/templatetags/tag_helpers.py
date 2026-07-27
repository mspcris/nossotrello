import hashlib
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def file_meta(fieldfile):
    """`{"name", "ext", "kind"}` de um anexo — nome real, extensão e tipo.

    Uma chamada só resolve tudo (1 query memoizada), então o template usa
    `{% with meta=att|file_meta %}` em vez de um filtro por atributo.
    """
    from boards.services.file_meta import file_meta as _meta
    try:
        return _meta(fieldfile)
    except Exception:
        return {"name": "", "ext": "", "kind": "file"}


@register.filter
def preview_thumb_url(fieldfile):
    """URL da miniatura de um anexo: 1ª página do PDF ou 1º frame do vídeo.

    Retorna '' quando não há como gerar — aí o template mostra a folha com a
    extensão. Gera sob demanda na 1ª vez (cobre anexos antigos) e memoiza.
    """
    from boards.services.attach_thumbs import thumb_url_for_fieldfile
    try:
        return thumb_url_for_fieldfile(fieldfile)
    except Exception:
        return ""


@register.filter
def quill_safe(value):
    """Sanitiza HTML (allowlist do Quill) e marca como safe pra render.

    Idempotente: serve tanto pra conteúdo já sanitizado quanto pra linhas
    legadas gravadas cruas — evita XSS armazenado ao usar |safe direto.
    """
    if not value:
        return ""
    from boards.views.helpers import sanitize_quill_html
    return mark_safe(sanitize_quill_html(str(value)))


@register.simple_tag
def counter_value(card):
    """Valor ao vivo de um card contador (None se não for contador)."""
    try:
        from boards.services.card_counters import compute_counter_value
        return compute_counter_value(card)
    except Exception:
        return None


@register.filter
def split_tags(value):
    """
    'tag1, tag2, tag3' -> ['tag1', 'tag2', 'tag3']
    """
    if not value:
        return []
    return [v.strip() for v in str(value).split(",") if v.strip()]


@register.filter
def tag_color(tag_name, tag_colors=None):
    """
    Se tag_colors vier (dict ou JSON), usa a cor salva.
    Senão, gera uma cor estável por hash (fallback).
    """
    if not tag_name:
        return "#888888"

    # 1) Tenta pegar cor salva (tag_colors pode ser JSON string ou dict)
    try:
        data = tag_colors

        if isinstance(tag_colors, str) and tag_colors.strip():
            import json
            data = json.loads(tag_colors)

        if isinstance(data, dict):
            c = (data.get(str(tag_name)) or "").strip()
            if c:
                return c
    except Exception:
        pass

    # 2) Fallback: cor estável por hash
    h = hashlib.md5(str(tag_name).encode("utf-8")).hexdigest()
    r = int(h[:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)

    r = (r + 150) // 2
    g = (g + 150) // 2
    b = (b + 150) // 2

    return f"rgb({r},{g},{b})"


# ================================================================
# NOVO FILTRO — trimstartswith
# Permite usar no template:
# {% if log.content|trimstartswith:"<pre><code" %}
# ================================================================
@register.filter
def trimstartswith(value, arg):
    """
    Remove espaços e compara se começa com o valor indicado.
    Garante que apenas blocos REAIS de código (<pre><code>) 
    ativem o modo de exibição de código.
    """
    if not isinstance(value, str):
        return False

    value_clean = value.strip().lower()
    arg_clean = str(arg).strip().lower()

    return value_clean.startswith(arg_clean)

