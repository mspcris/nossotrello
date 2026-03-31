from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0064_userprofile_notify_social"),
    ]

    operations = [
        migrations.AddField(
            model_name="socialpostcomment",
            name="seen_by_owner",
            field=models.BooleanField(default=False),
        ),
    ]
