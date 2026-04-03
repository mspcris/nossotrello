from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0085_socialpostversion"),
    ]

    operations = [
        migrations.AlterField(
            model_name="socialpostreaction",
            name="reaction",
            field=models.CharField(max_length=16),
        ),
    ]
