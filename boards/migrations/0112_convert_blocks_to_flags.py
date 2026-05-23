"""Converte todos os termos block → flag.

Decisão de produto: em vez de bloquear a publicação no ato (HTTP 400),
deixar o post aparecer com badge 'Em análise' (visível só pro autor),
oculto do feed, e cair na fila humana em /moderation/queue/.

Razão: a moderação humana decide com contexto que a Camada 1 não tem.
Continua sendo possível adicionar termos novos como 'block' via admin
caso algum padrão extremo justifique bloqueio imediato.
"""
from django.db import migrations


def to_flag(apps, schema_editor):
    BannedTerm = apps.get_model("boards", "BannedTerm")
    BannedTerm.objects.filter(severity="block").update(severity="flag")


def to_block(apps, schema_editor):
    # Reverter é semanticamente impossível (perde-se quais eram block e quais flag
    # antes desta migration). Como segunda melhor opção, NÃO mexer — quem reverte
    # vai reconfigurar manualmente pelo admin.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("boards", "0111_seed_banned_terms_short"),
    ]
    operations = [
        migrations.RunPython(to_flag, to_block),
    ]
