"""Converte SocialPosts legados de convite de quadro pro novo marker
'__board_invite__:<board_id>:<invited_user_id>'.

Texto legado tinha o formato:
    📋 <inviter> convidou <invited> para o quadro: <board_name>
    🔗 http(s)://.../board/<board_id>/

Como nem sempre conseguimos resolver o id do convidado pelo nome
(display_name/handle/email são ambíguos), aceitamos invited_id=0 como
fallback — o card ainda renderiza com o quadro + o inviter (post.user).
"""

import re

from django.db import migrations


LEGACY_RE = re.compile(
    r"^📋\s+(?P<inviter>.+?)\s+convidou\s+(?P<invited>.+?)\s+para\s+o\s+quadro:\s+(?P<board>.+?)\s*\n🔗\s+\S*?/board/(?P<board_id>\d+)/?\b",
    re.DOTALL,
)


def _resolve_invited_id(User, invited_label: str, board_id: int) -> int:
    """Tenta encontrar o usuário convidado pelo display_name/handle/email.
    Retorna 0 se ambíguo ou não encontrado."""
    label = (invited_label or "").strip()
    if not label:
        return 0

    if label.startswith("@"):
        handle = label[1:].strip()
        qs = User.objects.filter(profile__handle__iexact=handle)
        ids = list(qs.values_list("id", flat=True)[:2])
        if len(ids) == 1:
            return ids[0]
        return 0

    if "@" in label:
        qs = User.objects.filter(email__iexact=label)
        ids = list(qs.values_list("id", flat=True)[:2])
        if len(ids) == 1:
            return ids[0]

    qs = User.objects.filter(profile__display_name__iexact=label)
    ids = list(qs.values_list("id", flat=True)[:2])
    if len(ids) == 1:
        return ids[0]

    # Tenta restringir aos membros do board (mais provável de ser único)
    BoardMembership = User._meta.apps.get_model("boards", "BoardMembership")
    member_ids = set(
        BoardMembership.objects.filter(board_id=board_id).values_list("user_id", flat=True)
    )
    if member_ids:
        narrowed = [i for i in ids if i in member_ids]
        if len(narrowed) == 1:
            return narrowed[0]

    return 0


def convert_legacy(apps, schema_editor):
    SocialPost = apps.get_model("boards", "SocialPost")
    User = apps.get_model("auth", "User")

    qs = SocialPost.objects.filter(text__startswith="📋 ")
    for post in qs.iterator():
        m = LEGACY_RE.match(post.text or "")
        if not m:
            continue
        try:
            board_id = int(m.group("board_id"))
        except (TypeError, ValueError):
            continue
        invited_id = _resolve_invited_id(User, m.group("invited"), board_id)
        post.text = f"__board_invite__:{board_id}:{invited_id}"
        post.save(update_fields=["text"])


def noop_reverse(apps, schema_editor):
    # Sem rollback: o texto original não pode ser reconstruído a partir do marker.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0103_reactivate_legacy_avatar_cover_posts"),
    ]

    operations = [
        migrations.RunPython(convert_legacy, noop_reverse),
    ]
