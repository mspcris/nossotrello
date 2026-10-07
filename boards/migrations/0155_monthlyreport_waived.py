# Entrega mensal: liberação (dispensa) de um mês por admin do quadro.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0154_idcamim_inativo'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='monthlyreportentry',
            name='status',
            field=models.CharField(choices=[('pending', 'Pendente'), ('validating', 'Validando'), ('delivered', 'Entregue'), ('rejected', 'Anexo reprovado'), ('skipped', 'Sem anexo (histórico)'), ('waived', 'Liberado (dispensado)')], default='pending', max_length=12),
        ),
        migrations.AddField(
            model_name='monthlyreportentry',
            name='waived_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='monthlyreportentry',
            name='waived_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='monthly_entries_waived', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='monthlyreportentry',
            name='waived_reason',
            field=models.CharField(blank=True, default='', max_length=300),
        ),
    ]
