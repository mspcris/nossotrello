"""Move interações legadas (comments + reactions) de reposts pra publicação original.

Antes desta mudança, cada repost acumulava comments/reactions próprios. A nova
regra é: toda interação fica concentrada na publicação raiz (shared_from).
Esta migration alinha o histórico ao novo comportamento.

Edge cases:
- Comments: reassign post_id = shared_from_id. Mantém autor/timestamp.
- Reactions: idem, mas pode haver conflito de unique (user, post) se o usuário
  reagiu tanto ao repost quanto ao original. Nesse caso, MANTÉM a reação ao
  original e descarta a do repost (mais antiga ou mais nova — a do original
  é "canônica").
"""
from __future__ import annotations

from django.db import migrations


def forward(apps, schema_editor):
    SocialPost = apps.get_model("boards", "SocialPost")
    SocialPostComment = apps.get_model("boards", "SocialPostComment")
    SocialPostReaction = apps.get_model("boards", "SocialPostReaction")

    repost_ids = list(
        SocialPost.objects.filter(shared_from__isnull=False)
        .values_list("id", "shared_from_id")
    )
    if not repost_ids:
        return

    # Comments: reassign direto. Sem conflito de unique constraint.
    for repost_id, origin_id in repost_ids:
        SocialPostComment.objects.filter(post_id=repost_id).update(post_id=origin_id)

    # Reactions: tem unique (user, post). Resolve conflito mantendo a reação
    # já existente no original e descartando a do repost.
    for repost_id, origin_id in repost_ids:
        repost_reacts = list(
            SocialPostReaction.objects.filter(post_id=repost_id)
            .values_list("id", "user_id")
        )
        if not repost_reacts:
            continue
        user_ids_with_origin = set(
            SocialPostReaction.objects.filter(post_id=origin_id)
            .values_list("user_id", flat=True)
        )
        for react_id, user_id in repost_reacts:
            if user_id in user_ids_with_origin:
                SocialPostReaction.objects.filter(id=react_id).delete()
            else:
                SocialPostReaction.objects.filter(id=react_id).update(post_id=origin_id)


def backward(apps, schema_editor):
    """Não há como reverter — informação de origem (repost vs original) se perde."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0113_socialpost_mood_camilinho"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
