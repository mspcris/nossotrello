from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0092_healthchatmessage"),
    ]

    operations = [
        migrations.CreateModel(
            name="CamilaNews",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=250)),
                ("url", models.URLField(max_length=500)),
                ("fetched_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-fetched_at"],
                "indexes": [
                    models.Index(fields=["-fetched_at"], name="boards_cami_fetched_idx"),
                ],
            },
        ),
    ]
