# boards/templatetags/tag_helpers.py
import hashlib
from django import template

register = template.Library()


@register.filter
def split_tags(value):
    """
    Transforma 'tag1, tag2, tag3' em ['tag1', 'tag2', 'tag3'].
    """
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


@register.filter
def tag_color(tag_name):
    """
    Gera uma cor HEX (#RRGGBB) estável baseada no nome da tag.
    """
    if not tag_name:
        return "#888888"

    h = hashlib.md5(tag_name.encode("utf-8")).hexdigest()
    return f"#{h[:6]}"
