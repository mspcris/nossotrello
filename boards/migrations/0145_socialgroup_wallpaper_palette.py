from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0144_socialgroup_cover_image"),
    ]

    operations = [
        migrations.AddField(
            model_name="socialgroup",
            name="wallpaper",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="socialgroup",
            name="palette",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
    ]
