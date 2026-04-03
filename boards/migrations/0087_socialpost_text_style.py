from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0086_allow_custom_emoji_reactions"),
    ]

    operations = [
        migrations.AddField(
            model_name="socialpost",
            name="text_style",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
