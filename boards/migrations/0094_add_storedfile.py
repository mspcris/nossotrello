# boards/migrations/0094_add_storedfile.py
# Cria tabela StoredFile para armazenar arquivos no banco (bytea)

import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0093_camilanews'),
    ]

    operations = [
        migrations.CreateModel(
            name='StoredFile',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('original_name', models.CharField(blank=True, default='', max_length=500)),
                ('content_type', models.CharField(blank=True, default='application/octet-stream', max_length=200)),
                ('data', models.BinaryField()),
                ('size', models.BigIntegerField(default=0)),
                ('checksum', models.CharField(db_index=True, max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Arquivo armazenado',
                'verbose_name_plural': 'Arquivos armazenados',
                'indexes': [
                    models.Index(fields=['checksum'], name='storedfile_checksum_idx'),
                ],
            },
        ),
    ]
