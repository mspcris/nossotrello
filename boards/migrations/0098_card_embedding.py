from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0097_whats_new'),
    ]

    operations = [
        migrations.CreateModel(
            name='CardEmbedding',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('content_hash', models.CharField(db_index=True, max_length=64)),
                ('embedding', models.JSONField(default=list)),
                ('model', models.CharField(default='text-embedding-3-small', max_length=64)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('card', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='embedding', to='boards.card')),
            ],
            options={
                'indexes': [models.Index(fields=['content_hash'], name='cardemb_hash_idx')],
            },
        ),
    ]
