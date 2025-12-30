import hashlib
from django import template

register = template.Library()


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

