"""Stub state-only para satisfazer a cadeia de dependências.

A migration 0101 declara dependência desta migration, mas o arquivo nunca foi
versionado no git. A operação que existiria aqui é um `RenameIndex` no
`CamilaChatMessage`, mas na prática o estado do schema em todos os ambientes
já está com o nome novo. Para evitar erros de "relation does not exist" em
ambientes onde a operação física já aconteceu (ou nunca precisou acontecer),
declaramos a mudança SOMENTE no `state_operations` — Django passa a entender
que o modelo tem o nome novo do índice, sem tocar no banco.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0099_camilachatmessage"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RenameIndex(
                    model_name="camilachatmessage",
                    new_name="boards_cami_user_id_ba329e_idx",
                    old_name="boards_cami_user_id_msg_idx",
                ),
            ],
        ),
    ]
