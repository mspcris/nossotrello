from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0052_cardlog_attachment_deleted"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="terms_accepted",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="terms_accepted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="terms_version",
            field=models.CharField(blank=True, default="1.0", max_length=10),
        ),
    ]
