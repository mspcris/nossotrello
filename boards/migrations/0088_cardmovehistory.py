import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("boards", "0087_socialpost_text_style"),
    ]

    operations = [
        migrations.CreateModel(
            name="CardMoveHistory",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="card_moves",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("from_column", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="+",
                    to="boards.column",
                )),
                ("to_column", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="+",
                    to="boards.column",
                )),
                ("from_board", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="+",
                    to="boards.board",
                )),
                ("to_board", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="+",
                    to="boards.board",
                )),
            ],
            options={
                "verbose_name": "Histórico de movimentação",
                "verbose_name_plural": "Históricos de movimentação",
                "indexes": [
                    models.Index(fields=["user", "from_column"], name="cmh_user_from_col_idx"),
                ],
            },
        ),
    ]
