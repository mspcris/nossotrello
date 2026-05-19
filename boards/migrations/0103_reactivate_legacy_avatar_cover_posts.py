"""Reativa os avisos de "Nova foto de perfil" e "Atualizei minha foto de
capa" que a migration 0102 havia desativado em massa.

Decisão revisada: queremos que o histórico de capas/fotos antigas
continue aparecendo no reel "Novidades" (como aparece no perfil do
usuário). A regra de dedupe SÓ-O-MAIS-RECENTE continua valendo daqui em
diante via social_avatar_upload / social_cover_upload — sem acúmulo
para postagens novas, mas o legado permanece.
"""

from django.db import migrations


AVATAR_TEXT = "🤳 Nova foto de perfil!"
COVER_TEXT = "📸 Atualizei minha foto de capa!"


def reactivate_legacy(apps, schema_editor):
    SocialPost = apps.get_model("boards", "SocialPost")
    SocialPost.objects.filter(
        text__in=[AVATAR_TEXT, COVER_TEXT], is_active=False
    ).update(is_active=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0102_dedupe_avatar_cover_posts"),
    ]

    operations = [
        migrations.RunPython(reactivate_legacy, noop_reverse),
    ]
