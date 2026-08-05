from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0142_socialgroupchatmessage_photo"),
    ]

    operations = [
        migrations.AddField(
            model_name="socialgroup",
            name="theme_gallery_note",
            field=models.CharField(blank=True, default="", max_length=220),
        ),
        migrations.AddField(
            model_name="socialgroup",
            name="theme_gallery_title",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="socialgroup",
            name="theme_image_1",
            field=models.ImageField(blank=True, null=True, upload_to="social/groups/themes/"),
        ),
        migrations.AddField(
            model_name="socialgroup",
            name="theme_image_2",
            field=models.ImageField(blank=True, null=True, upload_to="social/groups/themes/"),
        ),
        migrations.AddField(
            model_name="socialgroup",
            name="theme_image_3",
            field=models.ImageField(blank=True, null=True, upload_to="social/groups/themes/"),
        ),
    ]
