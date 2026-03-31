from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0066_socialfriendship"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="unidade",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Unidade/setor onde trabalha — usado para sugestões de amigos",
                max_length=80,
            ),
        ),
    ]
