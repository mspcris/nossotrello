from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0104_convert_legacy_board_invite_posts"),
    ]

    operations = [
        migrations.AddField(
            model_name="socialpost",
            name="ai_food_dish",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
    ]
