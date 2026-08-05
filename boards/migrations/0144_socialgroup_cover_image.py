from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0143_socialgroup_theme_gallery_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="socialgroup",
            name="cover_image",
            field=models.ImageField(blank=True, null=True, upload_to="social/groups/covers/"),
        ),
    ]
