# boards/migrations/0096_merge_20260412_0215.py
# Merge entre duas leaves 0095:
#   - 0095_rename_boards_cami_fetched_idx_... (drift de models não commitado:
#     renames de index + mood choices expandidas + BigAutoField no CardMoveHistory.id)
#   - 0095_userprofile_boards_onboarding_done (flag de onboarding da home)
# Sem operações — só reconcilia o grafo.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0095_rename_boards_cami_fetched_idx_boards_cami_fetched_7bd7ae_idx_and_more'),
        ('boards', '0095_userprofile_boards_onboarding_done'),
    ]

    operations = []
