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
def tag_color(tag_name):
    """
    Gera uma cor estável para a tag, baseada em hash.
    """
    if not tag_name:
        return "#888888"

    h = hashlib.md5(str(tag_name).encode("utf-8")).hexdigest()
    r = int(h[:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)

    # suaviza um pouco as cores
    r = (r + 150) // 2
    g = (g + 150) // 2
    b = (b + 150) // 2

    return f"rgb({r},{g},{b})"
