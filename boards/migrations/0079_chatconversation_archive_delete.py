# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0078_termsacceptancelog'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatconversation',
            name='archived_by_a',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='chatconversation',
            name='archived_by_b',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='chatconversation',
            name='deleted_by_a',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='chatconversation',
            name='deleted_by_b',
            field=models.BooleanField(default=False),
        ),
    ]
