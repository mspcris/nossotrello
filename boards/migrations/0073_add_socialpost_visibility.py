from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ("boards", "0072_camila_pop_raw_text"),
    ]
    operations = [
        migrations.AddField(
            model_name="socialpost",
            name="visibility",
            field=models.CharField(
                choices=[("all", "Todos"), ("friends", "Apenas amigos")],
                default="all",
                max_length=10,
            ),
        ),
    ]
