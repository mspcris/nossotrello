from django.db import migrations


class Migration(migrations.Migration):
    """Merge dos 3 leaf nodes para unificar o grafo de migrations."""

    dependencies = [
        ("boards", "0055_rename_boards_soci_user_id_idx_boards_soci_user_id_a11109_idx_and_more"),
        ("boards", "0088_cardmovehistory"),
        ("boards", "0089_alter_camilapop_title_alter_chatsticker_id_and_more"),
    ]

    operations = []
