from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0141_alter_socialgroupmembership_role_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="socialgroupchatmessage",
            name="photo",
            field=models.ImageField(blank=True, null=True, upload_to="social/groups/chat/"),
        ),
    ]
