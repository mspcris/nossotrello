"""Seed dos termos curtos que precisam de match em palavra inteira.

Estes termos só podem ser usados depois da 0110 (que adicionou o campo
match_mode) — em modo word-boundary não estouram falsos positivos em
palavras inocentes (currículo, abundância, controla, Paula, respeitoso etc).

Curto ≠ menos sério. Estes são insultos diretos em ambiente corporativo.
"""
from django.db import migrations


# (term, display, severity, category, terms_clause, match_mode)
SHORT_TERMS = [
    # Anatomia/sexo — em rede corporativa, qualquer menção isolada é inadequada.
    ("cu", "cu", "block", "sexual", "4.5", "word"),
    ("pau", "pau (gíria)", "block", "sexual", "4.5", "word"),
    ("bunda", "bunda", "block", "sexual", "4.5", "word"),
    ("peito", "peito (em contexto sexual)", "flag", "sexual", "4.5", "word"),
    ("peitos", "peitos", "block", "sexual", "4.5", "word"),
    ("peitao", "peitão", "block", "sexual", "4.5", "word"),
    ("peituda", "peituda", "block", "sexual", "4.5", "word"),
    ("peitudo", "peitudo", "block", "sexual", "4.5", "word"),
    ("rola", "rola (gíria)", "block", "sexual", "4.5", "word"),
    ("pica", "pica (gíria)", "flag", "sexual", "4.5", "word"),  # pica de mosquito existe; flag
    ("comer", "comer (gíria sexual)", "flag", "sexual", "4.5", "word"),  # comer sanduíche também
    ("trepar", "trepar", "block", "sexual", "4.5", "word"),
    ("pênis", "pênis", "block", "sexual", "4.5", "word"),
    ("penis", "penis", "block", "sexual", "4.5", "word"),
    ("vagina", "vagina", "block", "sexual", "4.5", "word"),
    ("anus", "ânus", "block", "sexual", "4.5", "word"),

    # Insultos curtos
    ("fdp", "fdp", "block", "harassment", "4.5", "word"),  # também em 0109 mas word é mais seguro
    ("vsf", "vsf (vai se f**)", "block", "harassment", "4.5", "word"),
    ("pqp", "pqp (interjeição vulgar)", "flag", "harassment", "4.5", "word"),
    ("kct", "kct (eufemismo caralho)", "flag", "harassment", "4.5", "word"),

    # Ódio
    ("nego", "nego (slur quando isolado)", "flag", "hate", "4.5", "word"),  # 'nego que sim' é ok
]


def seed(apps, schema_editor):
    BannedTerm = apps.get_model("boards", "BannedTerm")
    for term, display, severity, category, clause, mode in SHORT_TERMS:
        BannedTerm.objects.update_or_create(
            term=term,
            defaults={
                "display": display,
                "severity": severity,
                "category": category,
                "terms_clause": clause,
                "match_mode": mode,
                "active": True,
                "notes": "Seed curto/word-mode (migration 0111).",
            },
        )


def unseed(apps, schema_editor):
    BannedTerm = apps.get_model("boards", "BannedTerm")
    BannedTerm.objects.filter(
        term__in=[t[0] for t in SHORT_TERMS],
        notes="Seed curto/word-mode (migration 0111).",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("boards", "0110_bannedterm_match_mode"),
    ]
    operations = [
        migrations.RunPython(seed, unseed),
    ]
