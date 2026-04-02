# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0082_socialpost_gif_sticker'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatmessage',
            name='notified',
            field=models.BooleanField(default=False),
        ),
    ]
