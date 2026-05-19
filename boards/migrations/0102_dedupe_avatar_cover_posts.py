"""Soft-delete avisos antigos de "Nova foto de perfil" e "Atualizei minha foto
de capa" para cada usuário, deixando só o mais recente ativo. Limpa um
acúmulo retroativo (antes do fix em social_avatar_upload/social_cover_upload
que passa a fazer isso a cada upload novo)."""

from django.db import migrations
from django.db.models import Max


AVATAR_TEXT = "🤳 Nova foto de perfil!"
COVER_TEXT = "📸 Atualizei minha foto de capa!"


def cleanup_old_announcements(apps, schema_editor):
    SocialPost = apps.get_model("boards", "SocialPost")

    for text in (AVATAR_TEXT, COVER_TEXT):
        latest_ids = list(
            SocialPost.objects
            .filter(text=text, is_active=True)
            .values("user_id")
            .annotate(latest_id=Max("id"))
            .values_list("latest_id", flat=True)
        )
        SocialPost.objects.filter(
            text=text, is_active=True
        ).exclude(id__in=latest_ids).update(is_active=False)


def noop_reverse(apps, schema_editor):
    # Reverter um soft-delete deste tipo não traz valor; mantemos no-op.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0101_userprofile_camim_sub"),
    ]

    operations = [
        migrations.RunPython(cleanup_old_announcements, noop_reverse),
    ]
