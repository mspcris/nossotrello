from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0084_add_social_comment_reaction"),
    ]

    operations = [
        migrations.CreateModel(
            name="SocialPostVersion",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("text", models.TextField(blank=True, default="")),
                ("photo", models.ImageField(blank=True, null=True, upload_to="social/versions/")),
                ("video", models.FileField(blank=True, null=True, upload_to="social/versions/videos/")),
                ("gif_url", models.URLField(blank=True, default="")),
                ("sticker_url", models.URLField(blank=True, default="")),
                ("visibility", models.CharField(default="all", max_length=10)),
                ("edited_at", models.DateTimeField(auto_now_add=True)),
                ("post", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="versions", to="boards.socialpost")),
            ],
            options={
                "ordering": ["-edited_at"],
            },
        ),
    ]
