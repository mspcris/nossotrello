# boards/migrations/0095_userprofile_boards_onboarding_done.py
# Flag de onboarding da home de quadros.
# Marca se o usuário já viu o modal de boas-vindas + o "QUADRO DE EXEMPLO"
# provisionado no primeiro acesso. Uma vez True, não recria nada.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0094_add_storedfile'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='boards_onboarding_done',
            field=models.BooleanField(default=False),
        ),
    ]
