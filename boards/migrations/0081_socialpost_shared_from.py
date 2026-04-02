# Generated manually

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0080_chatsticker_and_sticker_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='socialpost',
            name='shared_from',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='reposts',
                to='boards.socialpost',
            ),
        ),
    ]
