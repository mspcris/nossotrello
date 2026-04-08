from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0090_merge_all_leaves"),
    ]

    operations = [
        migrations.AddField(
            model_name="socialpostview",
            name="source",
            field=models.CharField(
                choices=[("profile", "Perfil"), ("feed", "Feed/Novidades")],
                default="profile",
                max_length=10,
            ),
        ),
        migrations.AlterUniqueTogether(
            name="socialpostview",
            unique_together={("post", "viewer", "source")},
        ),
        migrations.AddIndex(
            model_name="socialpostview",
            index=models.Index(fields=["post", "source"], name="boards_soci_post_id_source_idx"),
        ),
    ]
