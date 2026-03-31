from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0063_camilaconfig"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="notify_social",
            field=models.BooleanField(default=True),
        ),
    ]
