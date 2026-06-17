from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0129_card_counter_days_card_counter_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="code_block_style",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Cor do bloco de código do usuário: {bg, fg}. Vale só para "
                    "blocos criados daqui pra frente (a cor é gravada em cada bloco "
                    "novo); os antigos não mudam."
                ),
            ),
        ),
    ]
