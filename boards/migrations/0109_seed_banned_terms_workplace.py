"""Reforço da lista de termos banidos — contexto profissional/empresarial.

Esta é uma rede social CORPORATIVA. O critério é mais estrito que em redes
sociais públicas: termos que seriam apenas "informais" em outros contextos
aqui violam o decoro profissional (cláusula 4.5 dos Termos de Uso).

Esta migration NÃO adiciona termos curtos (2-4 letras) por causa do matching
substring atual (que causaria falsos positivos massivos — ver os comentários
no commit). Quando o matcher for upgradado para modo word-boundary, lançar
0110 com: cu, pau, rola, bunda, peito, ano (sufixo), comer, pica, etc.
"""
from django.db import migrations


# (term_normalizado, display, severity, category, terms_clause)
# Lembrete: o term aqui já vai pra normalize() — o que o usuário digitar é
# normalizado antes de comparar. Sempre minúsculo, sem acento, sem separador.
WORKPLACE_TERMS = [
    # ─────────────────────────────────────────────────────────────
    # SEXUAL — block (jamais aceitável em contexto profissional)
    # ─────────────────────────────────────────────────────────────
    ("sexo", "sexo", "block", "sexual", "4.5"),
    ("transar", "transar", "block", "sexual", "4.5"),
    ("transei", "transei", "block", "sexual", "4.5"),
    ("transou", "transou", "block", "sexual", "4.5"),
    ("transando", "transando", "block", "sexual", "4.5"),
    ("transamos", "transamos", "block", "sexual", "4.5"),
    ("foder", "foder", "block", "sexual", "4.5"),
    ("fodi", "fodi", "block", "sexual", "4.5"),
    ("fodeu", "fodeu", "block", "sexual", "4.5"),
    ("fodendo", "fodendo", "block", "sexual", "4.5"),
    ("fodida", "fodida", "block", "sexual", "4.5"),
    ("fodido", "fodido", "block", "sexual", "4.5"),
    ("fuder", "fuder", "block", "sexual", "4.5"),
    ("fudeu", "fudeu", "block", "sexual", "4.5"),
    ("fudendo", "fudendo", "block", "sexual", "4.5"),
    ("fudida", "fudida", "block", "sexual", "4.5"),
    ("fudido", "fudido", "block", "sexual", "4.5"),
    ("chupar", "chupar", "block", "sexual", "4.5"),
    ("chupei", "chupei", "block", "sexual", "4.5"),
    ("chupou", "chupou", "block", "sexual", "4.5"),
    ("chupando", "chupando", "block", "sexual", "4.5"),
    ("chupada", "chupada", "block", "sexual", "4.5"),
    ("chupado", "chupado", "block", "sexual", "4.5"),
    ("gozada", "gozada", "block", "sexual", "4.5"),
    ("masturbar", "masturbar", "block", "sexual", "4.5"),
    ("masturbei", "masturbei", "block", "sexual", "4.5"),
    ("masturbacao", "masturbação", "block", "sexual", "4.5"),
    ("caralho", "caralho", "block", "sexual", "4.5"),
    ("porra", "porra", "block", "sexual", "4.5"),
    ("tesao", "tesão", "block", "sexual", "4.5"),
    ("tesudo", "tesudo", "block", "sexual", "4.5"),
    ("tesuda", "tesuda", "block", "sexual", "4.5"),
    ("gostoso", "gostoso", "block", "sexual", "4.5"),
    ("gostosa", "gostosa", "block", "sexual", "4.5"),
    ("safado", "safado", "block", "sexual", "4.5"),
    ("safada", "safada", "block", "sexual", "4.5"),
    ("escroto", "escroto", "block", "sexual", "4.5"),
    ("escrota", "escrota", "block", "sexual", "4.5"),
    ("cuzao", "cuzão", "block", "sexual", "4.5"),
    ("cuzona", "cuzona", "block", "sexual", "4.5"),
    ("xereca", "xereca", "block", "sexual", "4.5"),
    ("punheteiro", "punheteiro", "block", "sexual", "4.5"),

    # ─────────────────────────────────────────────────────────────
    # XINGAMENTO/ASSÉDIO — block
    # ─────────────────────────────────────────────────────────────
    ("corno", "corno", "block", "harassment", "4.5"),
    ("corna", "corna", "block", "harassment", "4.5"),
    ("arrombado", "arrombado", "block", "harassment", "4.5"),
    ("arrombada", "arrombada", "block", "harassment", "4.5"),
    ("desgracado", "desgraçado", "block", "harassment", "4.5"),
    ("desgracada", "desgraçada", "block", "harassment", "4.5"),
    ("desgraca", "desgraça", "block", "harassment", "4.5"),
    ("imbecil", "imbecil", "block", "harassment", "4.5"),
    ("idiota", "idiota", "block", "harassment", "4.5"),
    ("otario", "otário", "block", "harassment", "4.5"),
    ("otaria", "otária", "block", "harassment", "4.5"),
    ("babaca", "babaca", "block", "harassment", "4.5"),
    ("fdp", "fdp", "block", "harassment", "4.5"),
    ("bostao", "bostão", "block", "harassment", "4.5"),

    # ─────────────────────────────────────────────────────────────
    # ÓDIO/RACISMO/HOMOFOBIA — block (zero tolerância em ambiente
    # corporativo; CLT trata como justa causa pela alínea j do art. 482)
    # ─────────────────────────────────────────────────────────────
    ("traveco", "traveco", "block", "hate", "4.5"),
    ("mongoloide", "mongoloide", "block", "hate", "4.5"),
    ("favelado", "favelado", "block", "hate", "4.5"),
    ("favelada", "favelada", "block", "hate", "4.5"),

    # ─────────────────────────────────────────────────────────────
    # FLAG — vai pra fila humana (interjeições/usos ambíguos)
    # ─────────────────────────────────────────────────────────────
    ("merda", "merda", "flag", "harassment", "4.5"),
    ("besta", "besta", "flag", "harassment", "4.5"),
    ("burro", "burro (insulto)", "flag", "harassment", "4.5"),
    ("burra", "burra (insulto)", "flag", "harassment", "4.5"),
]


# Termos que já existiam como 'flag' e agora viram 'block' no contexto corporativo.
ESCALATE_TO_BLOCK = ["viado", "bicha", "macaco", "matar", "retardado", "vagabunda", "vagabundo"]


def seed(apps, schema_editor):
    BannedTerm = apps.get_model("boards", "BannedTerm")

    # 1) Adiciona/atualiza os termos novos
    for term, display, severity, category, clause in WORKPLACE_TERMS:
        BannedTerm.objects.update_or_create(
            term=term,
            defaults={
                "display": display,
                "severity": severity,
                "category": category,
                "terms_clause": clause,
                "active": True,
                "notes": "Seed corporativo (migration 0109).",
            },
        )

    # 2) Escala flag → block nos termos já existentes
    for term in ESCALATE_TO_BLOCK:
        BannedTerm.objects.filter(term=term).update(severity="block", terms_clause="4.5")


def unseed(apps, schema_editor):
    BannedTerm = apps.get_model("boards", "BannedTerm")
    BannedTerm.objects.filter(
        term__in=[t[0] for t in WORKPLACE_TERMS],
        notes="Seed corporativo (migration 0109).",
    ).delete()
    # Reverte escalada
    for term in ESCALATE_TO_BLOCK:
        BannedTerm.objects.filter(term=term).update(severity="flag", terms_clause="4.4")


class Migration(migrations.Migration):
    dependencies = [
        ("boards", "0108_seed_banned_terms"),
    ]
    operations = [
        migrations.RunPython(seed, unseed),
    ]
