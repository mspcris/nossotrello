from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0105_socialpost_ai_food_dish"),
    ]

    operations = [
        migrations.AddField(
            model_name="socialpost",
            name="video_poster",
            field=models.ImageField(blank=True, null=True, upload_to="social/posters/"),
        ),
    ]
