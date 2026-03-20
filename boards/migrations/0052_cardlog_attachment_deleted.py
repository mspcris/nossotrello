from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0051_add_performance_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="cardlog",
            name="attachment_deleted",
            field=models.BooleanField(default=False),
        ),
    ]
