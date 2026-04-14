# boards/management/commands/sync_whats_new.py
"""
Importa commits `feat:` do git como entradas na timeline "Novidades".

- Ignora `fix:`, `chore:`, `docs:`, `ci:`, `perf:` (só inclui `feat`).
- Usa o hash do commit como chave idempotente (unique).
- Texto humanizado: remove prefixo conventional-commit, capitaliza.
- Emoji é inferido por palavras-chave (compartilhar→📤, chat→💬, etc.).

Uso:
    python manage.py sync_whats_new              # importa últimos 200 commits
    python manage.py sync_whats_new --limit 500
    python manage.py sync_whats_new --since "2026-01-01"
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime

from boards.models import WhatsNewItem


FEAT_RE = re.compile(r"^feat(\([^)]*\))?\s*:\s*(.+)$", re.IGNORECASE)

# Palavras/padrões que indicam um commit NÃO-VISÍVEL ao usuário final.
# Se bate aqui, o item é criado com is_published=False (fica pro admin decidir).
TECHNICAL_RE = re.compile(
    r"\b("
    r"pubsub|websocket|channels|rabbitmq|redis|"
    r"migration|migra[cç][aã]o|"
    r"storage|bytea|postgres|database|db\b|"
    r"rename|refactor|cleanup|"
    r"ci\b|deploy|nginx|docker|gunicorn|"
    r"endpoint\s+interno|polling|cron\b|"
    r"debug\s+log|threading"
    r")\b",
    re.IGNORECASE,
)

EMOJI_RULES = [
    (r"\b(share|compartilh)", "📤"),
    (r"\b(chat|mensag)", "💬"),
    (r"\b(notif|alert)", "🔔"),
    (r"\b(onboard|primeiro acesso|tour)", "🎓"),
    (r"\b(mood|humor|checkin|check-in|bem.?estar|health|saúde|saude)", "💚"),
    (r"\b(calend|agenda|prazo|due)", "📅"),
    (r"\b(cam[ií]la|ai|ia\b|news|notícia|noticia)", "🤖"),
    (r"\b(mobile|app|flutter)", "📱"),
    (r"\b(websocket|realtime|ws|pubsub|pub/sub|channels)", "⚡"),
    (r"\b(upload|anex|attach|arquiv|file|storage)", "📎"),
    (r"\b(post|feed|social|reel)", "📸"),
    (r"\b(board|quadro|coluna|column)", "🗂️"),
    (r"\b(tag|etiqueta)", "🏷️"),
    (r"\b(friend|amigo|rede)", "🤝"),
    (r"\b(ui|hover|layout|design|tema|theme)", "🎨"),
]


def _pick_emoji(text: str) -> str:
    low = text.lower()
    for pat, emoji in EMOJI_RULES:
        if re.search(pat, low):
            return emoji
    return "✨"


def _humanize(subject: str) -> str:
    """Remove prefixo `feat(...)?:` e capitaliza a primeira letra."""
    m = FEAT_RE.match(subject)
    if not m:
        return subject.strip()
    body = m.group(2).strip()
    if body:
        body = body[0].upper() + body[1:]
    return body


class Command(BaseCommand):
    help = "Importa commits feat: do git para a timeline Novidades."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=200)
        parser.add_argument("--since", type=str, default="")

    def handle(self, *args, **opts):
        limit = opts["limit"]
        since = opts["since"]

        cmd = [
            "git", "log",
            f"--max-count={limit}",
            "--pretty=format:%H|%aI|%s",
        ]
        if since:
            cmd.insert(2, f"--since={since}")

        try:
            out = subprocess.check_output(cmd, text=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            self.stderr.write(f"git log falhou: {e}")
            return

        created = 0
        skipped = 0
        for line in out.splitlines():
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            commit_hash, iso_dt, subject = parts
            if not FEAT_RE.match(subject):
                continue

            if WhatsNewItem.objects.filter(commit_hash=commit_hash).exists():
                skipped += 1
                continue

            title = _humanize(subject)
            dt = parse_datetime(iso_dt) or datetime.fromisoformat(iso_dt)

            # Commits técnicos entram despublicados — admin decide se libera.
            is_published = not bool(TECHNICAL_RE.search(title))

            WhatsNewItem.objects.create(
                commit_hash=commit_hash,
                emoji=_pick_emoji(title),
                title=title[:200],
                description="",
                published_at=dt,
                is_published=is_published,
            )
            created += 1
            self.stdout.write(self.style.SUCCESS(f"+ {commit_hash[:8]} {title}"))

        self.stdout.write(self.style.SUCCESS(
            f"Concluído. Criados: {created}. Já existiam: {skipped}."
        ))
