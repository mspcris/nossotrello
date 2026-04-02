# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0081_socialpost_shared_from'),
    ]

    operations = [
        migrations.AddField(
            model_name='socialpost',
            name='gif_url',
            field=models.URLField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='socialpost',
            name='sticker_url',
            field=models.URLField(blank=True, default=''),
        ),
    ]
