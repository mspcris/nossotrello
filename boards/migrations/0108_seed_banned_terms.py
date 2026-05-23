"""Seed inicial de BannedTerm — lista mínima para Camada 1.

Termos são guardados em forma normalizada (minúsculas, sem acentos, sem
separadores) — vide boards/services/moderation/normalize.py.

A lista aqui é DELIBERADAMENTE curta e conservadora. Use o admin pra
adicionar variações regionais / específicas do contexto da CAMIM.
"""
from django.db import migrations


# (term_normalizado, display, severity, category, terms_clause)
INITIAL_TERMS = [
    # --- Sexual explícito ---
    ("pornografia", "pornografia", "block", "sexual", "4.4"),
    ("porno", "pornô", "block", "sexual", "4.4"),
    ("nudes", "nudes", "block", "sexual", "4.4"),
    ("gozay", "gozay", "block", "sexual", "4.4"),
    ("gozar", "gozar", "flag", "sexual", "4.4"),
    ("siririca", "siririca", "block", "sexual", "4.4"),
    ("punheta", "punheta", "block", "sexual", "4.4"),
    ("boquete", "boquete", "block", "sexual", "4.4"),
    ("xoxota", "xoxota", "block", "sexual", "4.4"),
    ("buceta", "buceta", "block", "sexual", "4.4"),
    ("piroca", "piroca", "block", "sexual", "4.4"),
    ("pinto", "pinto", "flag", "sexual", "4.4"),
    ("dorme77", "dorme77", "flag", "sexual", "4.4"),

    # --- Discurso de ódio (mínimo) ---
    # Termos racistas/homofóbicos clássicos. Curadoria humana deve expandir.
    ("viado", "viado", "flag", "hate", "4.4"),
    ("bicha", "bicha", "flag", "hate", "4.4"),
    ("macaco", "macaco", "flag", "hate", "4.4"),
    ("retardado", "retardado", "flag", "hate", "4.4"),
    ("mongol", "mongoloide", "flag", "hate", "4.4"),

    # --- Ameaças / violência ---
    ("teror", "terror", "flag", "violence", "4.4"),  # 'terror' normalizado
    ("matar", "matar", "flag", "violence", "4.4"),
    ("estuprar", "estuprar", "block", "violence", "4.4"),

    # --- Assédio / xingamentos pesados ---
    ("vagabunda", "vagabunda", "flag", "harassment", "4.4"),
    ("vagabundo", "vagabundo", "flag", "harassment", "4.4"),
    ("filhadaputa", "filha da puta", "block", "harassment", "4.4"),
    ("filhodaputa", "filho da puta", "block", "harassment", "4.4"),

    # --- PII / vazamento de prontuário (item 4.4) ---
    ("prontuario", "prontuário", "flag", "pii", "4.4"),
    ("cpf", "CPF", "flag", "pii", "4.4"),
]


def seed(apps, schema_editor):
    BannedTerm = apps.get_model("boards", "BannedTerm")
    for term, display, severity, category, clause in INITIAL_TERMS:
        BannedTerm.objects.update_or_create(
            term=term,
            defaults={
                "display": display,
                "severity": severity,
                "category": category,
                "terms_clause": clause,
                "active": True,
                "notes": "Seed inicial (migration 0108).",
            },
        )


def unseed(apps, schema_editor):
    BannedTerm = apps.get_model("boards", "BannedTerm")
    BannedTerm.objects.filter(
        term__in=[t[0] for t in INITIAL_TERMS],
        notes="Seed inicial (migration 0108).",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("boards", "0107_moderation_pipeline"),
    ]
    operations = [
        migrations.RunPython(seed, unseed),
    ]
