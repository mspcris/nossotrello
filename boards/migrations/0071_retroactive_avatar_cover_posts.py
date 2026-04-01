"""
Cria posts retroativos para usuários que alteraram avatar ou cover
mas não possuem nenhum post.
"""
from django.db import migrations


def create_retroactive_posts(apps, schema_editor):
    UserProfile = apps.get_model("boards", "UserProfile")
    SocialPost = apps.get_model("boards", "SocialPost")

    profiles = UserProfile.objects.select_related("user").all()
    for prof in profiles:
        user = prof.user
        has_posts = SocialPost.objects.filter(user=user).exists()
        if has_posts:
            continue

        # Se mudou avatar
        if prof.avatar:
            SocialPost.objects.create(
                user=user,
                text="🤳 Nova foto de perfil!",
                is_active=True,
            )

        # Se mudou cover
        if prof.cover_photo:
            SocialPost.objects.create(
                user=user,
                text="📸 Atualizei minha foto de capa!",
                is_active=True,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("boards", "0070_chat_softdelete"),
    ]

    operations = [
        migrations.RunPython(create_retroactive_posts, migrations.RunPython.noop),
    ]
