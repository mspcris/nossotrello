from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("boards", "0098_card_embedding"),
    ]

    operations = [
        migrations.CreateModel(
            name="CamilaChatMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("user", "Usuário"), ("assistant", "Camila")], max_length=10)),
                ("text", models.TextField()),
                ("source", models.CharField(choices=[("chat", "Chat direto"), ("react", "Reação automática")], default="chat", max_length=10)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="camila_messages", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["created_at"],
                "indexes": [
                    models.Index(fields=["user", "created_at"], name="boards_cami_user_id_msg_idx"),
                ],
            },
        ),
    ]
