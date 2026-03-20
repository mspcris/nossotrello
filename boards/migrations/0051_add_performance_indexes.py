from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0050_userboardpreference"),
    ]

    operations = [
        # Column indexes
        migrations.AddIndex(
            model_name="column",
            index=models.Index(fields=["board", "is_deleted"], name="col_board_deleted_idx"),
        ),
        migrations.AddIndex(
            model_name="column",
            index=models.Index(fields=["board", "position"], name="col_board_position_idx"),
        ),
        # Card indexes
        migrations.AddIndex(
            model_name="card",
            index=models.Index(fields=["column", "is_deleted"], name="card_col_deleted_idx"),
        ),
        migrations.AddIndex(
            model_name="card",
            index=models.Index(fields=["column", "position"], name="card_col_position_idx"),
        ),
        migrations.AddIndex(
            model_name="card",
            index=models.Index(fields=["due_date"], name="card_due_date_idx"),
        ),
        # CardLog indexes
        migrations.AddIndex(
            model_name="cardlog",
            index=models.Index(fields=["card", "created_at"], name="cardlog_card_created_idx"),
        ),
        migrations.AddIndex(
            model_name="cardlog",
            index=models.Index(fields=["actor", "created_at"], name="cardlog_actor_created_idx"),
        ),
    ]
