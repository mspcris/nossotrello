# boards/services/monthly_report.py
"""
Automação "Entrega mensal de relatório" (recorrência) — o motor.

Regra de negócio (docs/relatorio-mensal-automacao.md):

* Cada card da coluna é um relatório que precisa de UM anexo por mês
  calendário (ciclo = YYYY-MM). A cobrança é no dia `day` do mês (default 15).
* Anexo novo cai sempre no ciclo PENDENTE MAIS ANTIGO (≤ mês atual). Não dá
  para "cadastrar o mês seguinte" com o anterior faltando. Se o mês atual já
  foi entregue, o arquivo entra como adicional, sem rolar a data.
* Entregue -> IA (Groq) valida o arquivo; `reprovado` segura o ciclo (com
  "Aceitar mesmo assim"); qualquer outro veredito entrega: card fica
  NÃO entregue com data de entrega = dia 15 do próximo ciclo pendente.
* Dia 15 com o ciclo pendente -> e-mail aos gestores do posto (cadastro do
  Hesk + extras da regra) com cópia ao destinatário (Leonardo). Uma vez.
* Nada é apagado: anexo removido devolve o ciclo para pendente.

Quem é gerente vem de boards/services/hesk_gestores.py.
"""
import calendar
import io
import json
import logging
import re
import threading
import zipfile
from datetime import date, timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.db import connection
from django.utils import timezone
from django.utils.html import escape

logger = logging.getLogger(__name__)

ACTION = "monthly_report"
TRIGGER = "attach"
DEFAULT_DAY = 15
MAX_AI_ATTEMPTS = 3
MAX_TEXT_CHARS = 12000

MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
MESES_LONGO = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


# ---------------------------------------------------------------------------
# Calendário
# ---------------------------------------------------------------------------
def month_first(d: date) -> date:
    return d.replace(day=1)


def add_months(month: date, n: int) -> date:
    y, m = divmod(month.month - 1 + n, 12)
    return date(month.year + y, m + 1, 1)


def due_on(month: date, day: int = DEFAULT_DAY) -> date:
    last = calendar.monthrange(month.year, month.month)[1]
    return date(month.year, month.month, max(1, min(int(day or DEFAULT_DAY), last)))


def label(month: date) -> str:
    return f"{MESES[month.month - 1]}/{month.year}"


def label_long(month: date) -> str:
    return f"{MESES_LONGO[month.month - 1]} de {month.year}"


def today_local() -> date:
    return timezone.localdate()


_MONTH_WORDS = {
    "janeiro": 1, "jan": 1, "fevereiro": 2, "fev": 2, "marco": 3, "mar": 3, "abril": 4, "abr": 4,
    "maio": 5, "mai": 5, "junho": 6, "jun": 6, "julho": 7, "jul": 7, "agosto": 8, "ago": 8,
    "setembro": 9, "set": 9, "outubro": 10, "out": 10, "novembro": 11, "nov": 11,
    "dezembro": 12, "dez": 12,
}


def month_from_filename(name: str, today: date = None):
    """Mês citado no nome do arquivo ('…_Abril_de_2026.pdf', 'CTRL-Q 08-2026.xlsx').

    Sem ano no nome, assume a ocorrência mais recente que não está no futuro.
    None quando não há mês reconhecível."""
    import unicodedata
    today = today or today_local()
    raw = unicodedata.normalize("NFKD", name or "")
    raw = "".join(c for c in raw if not unicodedata.combining(c)).lower()
    raw = raw.rsplit("/", 1)[-1]
    raw = re.sub(r"\.[a-z0-9]{1,5}$", "", raw)
    tokens = re.split(r"[^a-z0-9]+", raw)

    # 2026-09 / 09-2026 / 09_2026
    m = re.search(r"(?<!\d)(20\d{2})[-_ .]?(0[1-9]|1[0-2])(?!\d)", raw)
    if m:
        return date(int(m.group(1)), int(m.group(2)), 1)
    m = re.search(r"(?<!\d)(0[1-9]|1[0-2])[-_ ./](20\d{2})(?!\d)", raw)
    if m:
        return date(int(m.group(2)), int(m.group(1)), 1)

    month = None
    for t in tokens:
        if t in _MONTH_WORDS and len(t) >= 3:
            month = _MONTH_WORDS[t]
            break
    if not month:
        return None
    year = None
    for t in tokens:
        if re.fullmatch(r"20\d{2}", t):
            year = int(t)
            break
        if re.fullmatch(r"\d{2}", t) and 20 <= int(t) <= 39:
            year = 2000 + int(t)
            break
    if year is None:
        year = today.year
        if date(year, month, 1) > month_first(today):
            year -= 1
    try:
        return date(year, month, 1)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Regra
# ---------------------------------------------------------------------------
def rule_params(rule) -> dict:
    p = dict(rule.params or {})
    try:
        day = int(p.get("day") or DEFAULT_DAY)
    except Exception:
        day = DEFAULT_DAY
    p["day"] = max(1, min(day, 28))
    p["recipient_email"] = (p.get("recipient_email") or "").strip().lower()
    p["extra_user_ids"] = [int(x) for x in (p.get("extra_user_ids") or []) if str(x).isdigit()]
    p["ai_validate"] = bool(p.get("ai_validate", True))
    p["ai_instructions"] = (p.get("ai_instructions") or "").strip()
    p["posto_nome"] = (p.get("posto_nome") or "").strip()
    return p


def start_month(rule) -> date:
    sm = (rule.params or {}).get("start_month") or ""
    m = re.match(r"^(\d{4})-(\d{2})$", str(sm))
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), 1)
        except Exception:
            pass
    created = getattr(rule, "created_at", None)
    if created:
        return month_first(timezone.localtime(created).date())
    return month_first(today_local())


def rule_for_column(column):
    from boards.models import ColumnAutomation
    if column is None:
        return None
    return (
        ColumnAutomation.objects.filter(column=column, action=ACTION, is_active=True)
        .order_by("id").first()
    )


def rule_for_card(card):
    return rule_for_column(getattr(card, "column", None))


def monthly_column_ids() -> set:
    """Colunas com a regra ativa — cache curto p/ o chip do card não custar query."""
    key = "monthly_report:column_ids:v1"
    ids = cache.get(key)
    if ids is None:
        from boards.models import ColumnAutomation
        ids = set(
            ColumnAutomation.objects.filter(action=ACTION, is_active=True)
            .values_list("column_id", flat=True)
        )
        cache.set(key, ids, 60)
    return ids


def invalidate_cache():
    cache.delete("monthly_report:column_ids:v1")


def posto_nome(rule) -> str:
    p = rule_params(rule)
    return p["posto_nome"] or (rule.column.board.name or "").strip()


def responsaveis(rule) -> list:
    """Gestores do posto (Hesk) + extras da regra. Lista de dicts
    {nome, email, telefone, source}. Sem duplicar e-mail."""
    from django.contrib.auth import get_user_model
    from boards.services import hesk_gestores

    out, seen = [], set()
    for g in hesk_gestores.gestores_do_posto(posto_nome(rule)):
        em = (g.get("email") or "").lower()
        if em and em in seen:
            continue
        seen.add(em)
        out.append({**g, "source": "hesk"})

    ids = rule_params(rule)["extra_user_ids"]
    if ids:
        User = get_user_model()
        for u in User.objects.filter(id__in=ids).select_related("profile"):
            em = (u.email or "").lower()
            if em in seen:
                continue
            seen.add(em)
            prof = getattr(u, "profile", None)
            nome = (getattr(prof, "display_name", "") or "").strip() or u.get_full_name() or u.get_username()
            out.append({
                "nome": nome, "email": em,
                "telefone": (getattr(prof, "telefone", "") or "").strip(),
                "source": "extra", "user_id": u.id,
            })
    return out


# ---------------------------------------------------------------------------
# Entradas (livro-razão)
# ---------------------------------------------------------------------------
def ensure_entry(rule, card, month: date, status: str = "pending"):
    from boards.models import MonthlyReportEntry
    day = rule_params(rule)["day"]
    entry, _created = MonthlyReportEntry.objects.get_or_create(
        card=card, month=month,
        defaults={"rule": rule, "due_on": due_on(month, day), "status": status},
    )
    return entry


def ensure_current(rule, card, today: date = None):
    """Garante a linha do mês corrente (se a regra já vale para ele)."""
    today = today or today_local()
    cur = month_first(today)
    if cur < start_month(rule):
        return None
    return ensure_entry(rule, card, cur)


def open_entries(card, upto: date):
    from boards.models import MonthlyReportEntry
    return (
        MonthlyReportEntry.objects.filter(
            card=card, month__lte=upto, status__in=["pending", "rejected"],
        ).order_by("month")
    )


def _card_link(card) -> str:
    site = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    try:
        return f"{site}/board/{card.column.board_id}/?card={card.id}"
    except Exception:
        return site


def _who(user) -> str:
    if not user:
        return "alguém"
    prof = getattr(user, "profile", None)
    dn = (getattr(prof, "display_name", "") or "").strip()
    return dn or user.get_full_name() or user.get_username()


def _log(card, actor, html: str):
    from boards.models import CardLog
    try:
        CardLog.objects.create(
            card=card,
            actor=actor if (actor and getattr(actor, "id", None)) else None,
            content=html,
        )
    except Exception:
        logger.debug("monthly_report: log falhou", exc_info=True)


def _bump_board(card):
    try:
        board = card.column.board
        board.version = (board.version or 0) + 1
        board.save(update_fields=["version"])
    except Exception:
        logger.debug("monthly_report: bump board falhou", exc_info=True)


def _bg(fn, *args):
    def run():
        try:
            fn(*args)
        except Exception:
            logger.exception("monthly_report: tarefa em background falhou")
        finally:
            try:
                connection.close()
            except Exception:
                pass
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Gatilho: anexo adicionado
# ---------------------------------------------------------------------------
def on_attachment_added(card, attachment, actor=None, sync: bool = False):
    """Atribui o anexo ao ciclo pendente mais antigo e dispara validação/entrega.

    Retorna a entrada afetada (ou None se a coluna não tem a regra).
    `sync=True` roda a IA/e-mails no mesmo thread (testes e comandos)."""
    rule = rule_for_card(card)
    if rule is None or attachment is None:
        return None

    today = today_local()
    cur = month_first(today)
    if cur < start_month(rule):
        return None
    ensure_current(rule, card, today)

    hint = month_from_filename(_display_name(attachment), today)
    candidates = list(open_entries(card, cur))
    entry = next((e for e in candidates if hint and e.month == hint), None) or (candidates[0] if candidates else None)
    if entry is None:
        # nada pendente: arquivo adicional do mês citado no nome (ou do corrente)
        from boards.models import MonthlyReportEntry
        entry = None
        if hint:
            entry = MonthlyReportEntry.objects.filter(card=card, month=hint).first()
        if entry is None:
            entry = MonthlyReportEntry.objects.filter(card=card, month=cur).first()
        if entry is None:
            return None
        extras = list(entry.extra_attachment_ids or [])
        if attachment.id not in extras and attachment.id != entry.attachment_id:
            extras.append(attachment.id)
            entry.extra_attachment_ids = extras
            entry.save(update_fields=["extra_attachment_ids", "updated_at"])
        _log(card, actor, (
            f"<p><strong>{escape(_who(actor))}</strong> anexou um arquivo adicional ao "
            f"relatório de <strong>{label(entry.month)}</strong>, que já estava entregue "
            f"(automação de entrega mensal).</p>"
        ))
        return entry

    p = rule_params(rule)
    entry.attachment = attachment
    entry.attached_at = timezone.now()
    entry.attached_by = actor if (actor and getattr(actor, "id", None)) else None
    entry.ai_verdict = ""
    entry.ai_summary = ""
    entry.ai_problems = []
    entry.ai_checked_at = None
    entry.ai_attempts = 0
    entry.accepted_by = None
    entry.notified_at = None
    if p["ai_validate"] and is_validatable(attachment):
        entry.status = "validating"
        entry.ai_status = "pending"
    else:
        entry.ai_status = "skipped" if p["ai_validate"] else "off"
    entry.save()

    _log(card, actor, (
        f"<p><strong>{escape(_who(actor))}</strong> anexou o relatório de "
        f"<strong>{label(entry.month)}</strong>"
        + (" — enviado para validação da IA." if entry.status == "validating" else ".")
        + "</p>"
    ))
    _bump_board(card)

    if sync:
        return finalize(entry.id, actor=actor) or entry
    _bg(finalize, entry.id)
    return entry


def finalize(entry_id: int, actor=None):
    """Roda a IA (se pendente) e decide: entregue ou reprovado."""
    from boards.models import MonthlyReportEntry
    entry = (
        MonthlyReportEntry.objects.select_related("card__column__board", "rule", "attachment", "attached_by")
        .filter(id=entry_id).first()
    )
    if entry is None or entry.status in ("delivered", "skipped"):
        return entry
    if entry.attachment_id is None:
        return entry

    if entry.ai_status == "pending":
        entry.ai_attempts = (entry.ai_attempts or 0) + 1
        result = None
        try:
            result = validate_with_ai(entry)
        except Exception:
            logger.exception("monthly_report: IA falhou entry=%s", entry.id)
        if result is None:
            if entry.ai_attempts < MAX_AI_ATTEMPTS:
                # fica "validating"; o scheduler tenta de novo
                entry.save(update_fields=["ai_attempts", "updated_at"])
                return entry
            entry.ai_status = "error"
            entry.ai_summary = "IA indisponível — anexo aceito sem validação."
        else:
            entry.ai_status = "done"
            entry.ai_verdict = result.get("veredito") or ""
            entry.ai_summary = (result.get("resumo") or "").strip()[:4000]
            probs = result.get("problemas") or []
            entry.ai_problems = [str(x)[:300] for x in probs][:10]
        entry.ai_checked_at = timezone.now()
        entry.save()

    if entry.ai_verdict == "reprovado":
        entry.status = "rejected"
        entry.save(update_fields=["status", "updated_at"])
        _log(entry.card, None, (
            f"<p>A IA <strong>reprovou</strong> o anexo do relatório de "
            f"<strong>{label(entry.month)}</strong>: {escape(entry.ai_summary[:300])}. "
            f"O mês continua pendente — um editor pode aceitar mesmo assim na aba Mensal.</p>"
        ))
        _bump_board(entry.card)
        _notify_rejected(entry)
        return entry

    return deliver(entry, actor=actor)


def deliver(entry, actor=None, accepted: bool = False):
    """Marca o ciclo como entregue e rola o card para o próximo pendente."""
    from boards.services.notifications import mark_card_undelivered

    rule = entry.rule
    p = rule_params(rule)
    card = entry.card

    entry.status = "delivered"
    if accepted:
        entry.accepted_by = actor if (actor and getattr(actor, "id", None)) else None
    entry.save()

    # próximo ciclo pendente (cria o mês seguinte se não houver nenhum aberto)
    nxt = open_entries(card, add_months(month_first(today_local()), 1)).first()
    if nxt is None:
        nxt = ensure_entry(rule, card, add_months(entry.month, 1))
        if nxt.status not in ("pending", "rejected"):
            nxt = ensure_entry(rule, card, add_months(month_first(today_local()), 1))

    mark_card_undelivered(card=card, clear_due=False)
    card.due_date = nxt.due_on
    card.save(update_fields=["due_date"])

    quem = f"<strong>{escape(_who(actor))}</strong> aceitou o anexo e " if accepted else ""
    _log(card, actor if accepted else None, (
        f"<p>{quem}Relatório de <strong>{label(entry.month)}</strong> entregue"
        + (f" — IA: {escape(entry.ai_verdict)}" if entry.ai_verdict else "")
        + f". Próxima entrega: <strong>{label(nxt.month)}</strong>, "
        f"até {nxt.due_on:%d/%m/%Y} (automação de entrega mensal).</p>"
    ))
    _bump_board(card)
    _notify_delivered(entry, p)
    return entry


def accept(entry, actor):
    if entry.status != "rejected":
        return entry
    return deliver(entry, actor=actor, accepted=True)


# ---------------------------------------------------------------------------
# Gatilho: anexo removido
# ---------------------------------------------------------------------------
def on_attachment_removed(card, attachment):
    from boards.models import MonthlyReportEntry, CardAttachment
    entry = MonthlyReportEntry.objects.filter(card=card, attachment=attachment).first()
    if entry is None:
        # era um "adicional"? só tira da lista
        for e in MonthlyReportEntry.objects.filter(card=card).exclude(extra_attachment_ids=[]):
            extras = [i for i in (e.extra_attachment_ids or []) if i != attachment.id]
            if extras != list(e.extra_attachment_ids or []):
                e.extra_attachment_ids = extras
                e.save(update_fields=["extra_attachment_ids", "updated_at"])
        return None

    extras = [i for i in (entry.extra_attachment_ids or []) if i != attachment.id]
    promoted = None
    if extras:
        promoted = CardAttachment.objects.filter(id__in=extras, card=card).order_by("created_at").first()
    if promoted is not None:
        entry.attachment = promoted
        entry.attached_at = promoted.created_at
        entry.attached_by = promoted.created_by
        entry.extra_attachment_ids = [i for i in extras if i != promoted.id]
        entry.save()
        _log(card, None, (
            f"<p>Anexo do relatório de <strong>{label(entry.month)}</strong> removido; "
            f"o arquivo adicional passou a valer como entrega.</p>"
        ))
        return entry

    entry.attachment = None
    entry.attached_at = None
    entry.attached_by = None
    entry.extra_attachment_ids = []
    entry.status = "pending"
    entry.ai_status = "off"
    entry.ai_verdict = ""
    entry.ai_summary = ""
    entry.ai_problems = []
    entry.accepted_by = None
    entry.reminded_at = None
    entry.save()

    # ciclos futuros criados automaticamente e ainda vazios saem da frente
    MonthlyReportEntry.objects.filter(
        card=card, status="pending", attachment__isnull=True,
        month__gt=max(entry.month, month_first(today_local())),
    ).delete()

    card.due_date = entry.due_on
    card.save(update_fields=["due_date"])
    _log(card, None, (
        f"<p>Anexo do relatório de <strong>{label(entry.month)}</strong> removido — "
        f"o mês voltou a ficar <strong>pendente</strong> (prazo {entry.due_on:%d/%m/%Y}).</p>"
    ))
    _bump_board(card)
    return entry


# ---------------------------------------------------------------------------
# Scheduler (dia 15 + retry da IA)
# ---------------------------------------------------------------------------
def run_scheduler(now=None) -> dict:
    from boards.models import Card, ColumnAutomation, MonthlyReportEntry

    now = now or timezone.now()
    today = timezone.localtime(now).date()
    stats = {"reminded": 0, "retried": 0, "created": 0}

    rules = (
        ColumnAutomation.objects.filter(action=ACTION, is_active=True)
        .select_related("column__board")
    )
    for rule in rules:
        cards = Card.objects.filter(column=rule.column, is_archived=False, counter_mode="")
        for card in cards:
            try:
                entry = ensure_current(rule, card, today)
                if entry is None:
                    continue
                if card.due_date is None:
                    first_open = open_entries(card, add_months(month_first(today), 1)).first()
                    if first_open is not None:
                        card.due_date = first_open.due_on
                        card.save(update_fields=["due_date"])
                overdue = list(
                    MonthlyReportEntry.objects.filter(
                        card=card, status="pending", attachment__isnull=True,
                        due_on__lte=today, reminded_at__isnull=True,
                    ).order_by("month")
                )
                if overdue:
                    _send_reminder(rule, card, overdue)
                    for e in overdue:
                        e.reminded_at = now
                        e.save(update_fields=["reminded_at", "updated_at"])
                    stats["reminded"] += 1
            except Exception:
                logger.exception("monthly_report: scheduler rule=%s card=%s", rule.id, card.id)

    # validações presas (thread morreu, Groq fora…)
    stuck = MonthlyReportEntry.objects.filter(
        status="validating", updated_at__lte=now - timedelta(minutes=3),
    )
    for entry in stuck:
        try:
            if (entry.ai_attempts or 0) >= MAX_AI_ATTEMPTS:
                entry.ai_status = "error"
                entry.ai_summary = "IA indisponível — anexo aceito sem validação."
                entry.ai_checked_at = now
                entry.save()
            finalize(entry.id)
            stats["retried"] += 1
        except Exception:
            logger.exception("monthly_report: retry entry=%s", entry.id)
    return stats


# ---------------------------------------------------------------------------
# IA (Groq)
# ---------------------------------------------------------------------------
_TEXT_EXTS = {"txt", "csv", "md", "tsv", "json"}
_VALIDATABLE = {"pdf", "xlsx", "xlsm", "docx"} | _TEXT_EXTS


def _ext(attachment) -> str:
    try:
        from boards.services.file_meta import file_meta
        meta = file_meta(attachment.file) or {}
        ext = (meta.get("ext") or "").lower().lstrip(".")
        if ext:
            return ext
    except Exception:
        pass
    name = (getattr(attachment.file, "name", "") or "")
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _display_name(attachment) -> str:
    try:
        from boards.services.file_meta import display_name
        return display_name(attachment.file) or (attachment.file.name or "arquivo")
    except Exception:
        return getattr(attachment.file, "name", "") or "arquivo"


def is_validatable(attachment) -> bool:
    return _ext(attachment) in _VALIDATABLE


def extract_text(attachment, limit: int = MAX_TEXT_CHARS):
    """Texto do anexo para a IA. None = formato sem texto (imagem, vídeo…)."""
    ext = _ext(attachment)
    if ext not in _VALIDATABLE:
        return None
    f = attachment.file
    f.open("rb")
    try:
        data = f.read()
    finally:
        try:
            f.close()
        except Exception:
            pass
    if not data:
        return ""
    text = ""
    try:
        if ext == "pdf":
            import pdfplumber
            parts = []
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                for page in pdf.pages[:20]:
                    parts.append(page.extract_text() or "")
                    if sum(len(x) for x in parts) > limit:
                        break
            text = "\n".join(parts)
        elif ext in ("xlsx", "xlsm"):
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            parts = []
            for ws in wb.worksheets[:4]:
                parts.append(f"## Planilha: {ws.title}")
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i >= 300:
                        parts.append("… (linhas omitidas)")
                        break
                    cells = ["" if v is None else str(v) for v in row]
                    if any(c.strip() for c in cells):
                        parts.append(" | ".join(cells).rstrip(" |"))
                if sum(len(x) for x in parts) > limit:
                    break
            text = "\n".join(parts)
        elif ext == "docx":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read("word/document.xml").decode("utf-8", errors="replace")
            xml = re.sub(r"</w:p>", "\n", xml)
            text = re.sub(r"<[^>]+>", "", xml)
        else:
            text = data.decode("utf-8", errors="replace")
    except Exception:
        logger.exception("monthly_report: extração de texto falhou (%s)", ext)
        return ""
    text = re.sub(r"[ \t]+", " ", text or "")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:limit]


def _groq_json(system: str, user: str, model: str = "") -> dict:
    import requests

    api_key = (getattr(settings, "GROQ_API_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY ausente")
    import os
    model = model or (os.getenv("GROQ_MODEL") or "").strip() or "openai/gpt-oss-120b"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 900,
        "response_format": {"type": "json_object"},
    }
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload, timeout=60,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    try:
        return json.loads(content)
    except Exception:
        m = re.search(r"\{.*\}", content, re.S)
        return json.loads(m.group(0)) if m else {}


_SYSTEM = (
    "Você é auditor administrativo da CAMIM (rede de clínicas no Rio de Janeiro). "
    "Recebe o conteúdo textual de um arquivo que um gerente de posto anexou como "
    "relatório mensal obrigatório. Avalie se o arquivo parece ser o relatório "
    "pedido, do posto e do mês indicados, e se está completo o bastante para uso. "
    "Seja objetivo e escreva em português do Brasil. Responda SOMENTE um JSON com "
    "as chaves: veredito ('aprovado' quando é claramente o relatório certo; "
    "'atencao' quando parece certo mas há lacunas, mês divergente ou dados "
    "estranhos; 'reprovado' SÓ quando o arquivo claramente NÃO é o relatório "
    "pedido — outro documento, vazio, ilegível), resumo (até 6 linhas com os "
    "números e fatos principais do relatório), problemas (lista curta de strings; "
    "vazia se não houver). Nunca reprove por formatação ou por falta de dados que "
    "não dá para conferir no texto."
)


def validate_with_ai(entry):
    """dict {veredito, resumo, problemas} — ou None quando a IA está indisponível."""
    text = extract_text(entry.attachment)
    if text is None:
        entry.ai_status = "skipped"
        return {"veredito": "", "resumo": "Arquivo sem texto (imagem/vídeo) — não validado pela IA.", "problemas": []}
    if not text.strip():
        return {
            "veredito": "atencao",
            "resumo": "Não foi possível extrair texto do arquivo (PDF escaneado ou planilha vazia).",
            "problemas": ["Sem texto legível para validar."],
        }
    rule = entry.rule
    p = rule_params(rule)
    card = entry.card
    instr = p["ai_instructions"]
    user = (
        f"Relatório esperado (título do card): {card.title}\n"
        f"Posto: {posto_nome(rule)}\n"
        f"Mês de referência da entrega: {label_long(entry.month)}\n"
        f"Nome do arquivo: {_display_name(entry.attachment)}\n"
        + (f"Instruções do gestor sobre o que o relatório deve conter: {instr}\n" if instr else "")
        + "\n--- CONTEÚDO DO ARQUIVO (texto extraído, pode estar truncado) ---\n"
        f"{text}\n--- FIM ---"
    )
    try:
        data = _groq_json(_SYSTEM, user)
    except Exception:
        logger.exception("monthly_report: Groq falhou entry=%s", entry.id)
        return None
    v = str(data.get("veredito") or "").strip().lower()
    v = {"aprovado": "aprovado", "atencao": "atencao", "atenção": "atencao", "reprovado": "reprovado"}.get(v, "atencao")
    probs = data.get("problemas") or []
    if not isinstance(probs, list):
        probs = [str(probs)]
    return {"veredito": v, "resumo": str(data.get("resumo") or "").strip(), "problemas": probs}


# ---------------------------------------------------------------------------
# E-mails / avisos
# ---------------------------------------------------------------------------
def _from_email():
    return getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", None)


def _send_mail(to: list, subject: str, body: str, cc: list = None):
    to = [t for t in (to or []) if t]
    cc = [c for c in (cc or []) if c and c not in to]
    if not to and cc:
        to, cc = cc, []
    if not to:
        logger.warning("monthly_report: e-mail sem destinatário (%s)", subject)
        return False
    try:
        msg = EmailMessage(subject=subject[:200], body=body, from_email=_from_email(), to=to, cc=cc)
        msg.send(fail_silently=True)
        return True
    except Exception:
        logger.exception("monthly_report: e-mail falhou (%s)", subject)
        return False


def _verdict_pt(v: str) -> str:
    return {"aprovado": "APROVADO", "atencao": "ATENÇÃO", "reprovado": "REPROVADO"}.get(v, "não validado")


def _notify_delivered(entry, p: dict):
    to = p["recipient_email"]
    card = entry.card
    posto = posto_nome(entry.rule)
    quem = _who(entry.attached_by)
    quando = timezone.localtime(entry.attached_at).strftime("%d/%m/%Y %H:%M") if entry.attached_at else ""
    arquivo = _display_name(entry.attachment) if entry.attachment else "(arquivo removido)"
    subject = f"[Tarefas] {posto} — {card.title} — {label(entry.month)} anexado"
    linhas = [
        f"Posto: {posto}",
        f"Relatório: {card.title}",
        f"Mês: {label_long(entry.month)}",
        f"Anexado por: {quem}" + (f" em {quando}" if quando else ""),
        f"Arquivo: {arquivo}",
        "",
    ]
    if entry.ai_status in ("done", "error", "skipped"):
        linhas.append(f"Validação da IA: {_verdict_pt(entry.ai_verdict)}")
        if entry.ai_summary:
            linhas += ["", "Resumo:", entry.ai_summary]
        if entry.ai_problems:
            linhas += ["", "Pontos de atenção:"] + [f"- {x}" for x in entry.ai_problems]
        linhas.append("")
    if entry.accepted_by_id:
        linhas.append(f"Aceito manualmente por {_who(entry.accepted_by)} após reprovação da IA.")
        linhas.append("")
    linhas.append(f"Abrir o card: {_card_link(card)}")
    ok = _send_mail([to], subject, "\n".join(linhas))
    if ok:
        entry.notified_at = timezone.now()
        entry.save(update_fields=["notified_at", "updated_at"])


def _notify_rejected(entry):
    p = rule_params(entry.rule)
    card = entry.card
    posto = posto_nome(entry.rule)
    subject = f"[Tarefas] {posto} — {card.title} — {label(entry.month)}: anexo REPROVADO pela IA"
    body = "\n".join([
        f"O arquivo anexado por {_who(entry.attached_by)} não parece ser o relatório pedido.",
        "",
        f"Posto: {posto}",
        f"Relatório: {card.title}",
        f"Mês: {label_long(entry.month)}",
        f"Arquivo: {_display_name(entry.attachment) if entry.attachment else ''}",
        "",
        f"Motivo (IA): {entry.ai_summary}",
    ] + ([""] + [f"- {x}" for x in entry.ai_problems] if entry.ai_problems else []) + [
        "",
        "O mês continua PENDENTE. Anexe o arquivo correto no card, ou peça a um editor "
        "para clicar em \"Aceitar mesmo assim\" na aba Mensal.",
        "",
        f"Abrir o card: {_card_link(card)}",
    ])
    to = []
    if entry.attached_by and (entry.attached_by.email or "").strip():
        to.append(entry.attached_by.email.strip())
    _send_mail(to, subject, body, cc=[p["recipient_email"]])
    # WhatsApp para quem anexou (se tiver)
    try:
        from boards.services.notifications import send_whatsapp, _safe_digits_phone
        prof = getattr(entry.attached_by, "profile", None) if entry.attached_by else None
        if prof is not None and getattr(prof, "notify_whatsapp", True):
            phone = _safe_digits_phone(getattr(prof, "telefone", "") or "")
            if phone:
                send_whatsapp(
                    user=entry.attached_by, phone_digits=phone, sync=True,
                    body=(
                        f"⚠️ O arquivo que você anexou em *{card.title}* ({posto}) não parece ser o "
                        f"relatório de {label(entry.month)}. Motivo: {entry.ai_summary[:300]}\n\n"
                        f"Anexe o arquivo correto: {_card_link(card)}"
                    ),
                )
    except Exception:
        logger.debug("monthly_report: WhatsApp de reprovação falhou", exc_info=True)


def _send_reminder(rule, card, entries: list):
    """Cobrança: um e-mail por card listando TODOS os meses vencidos sem anexo.
    Vai para os gestores do posto (nome citado no corpo) com cópia ao destinatário."""
    p = rule_params(rule)
    posto = posto_nome(rule)
    resp = responsaveis(rule)
    to = [r["email"] for r in resp if r.get("email")]
    nomes = [r["nome"] for r in resp if r.get("nome")]
    meses = [label_long(e.month) for e in entries]
    if len(meses) == 1:
        meses_txt = meses[0]
    else:
        meses_txt = ", ".join(meses[:-1]) + " e " + meses[-1]
    plural = len(entries) > 1
    subject = (
        f"[Tarefas] {posto} — {card.title} — "
        + (f"{len(entries)} meses sem relatório ({', '.join(label(e.month) for e in entries)})"
           if plural else f"{label(entries[0].month)} NÃO anexado")
    )
    saud = ("Olá, " + (" e ".join(nomes) if len(nomes) <= 2 else ", ".join(nomes[:-1]) + " e " + nomes[-1])
            + f" (posto {posto}),") if nomes else f"Olá, gestão do posto {posto},"
    aviso = ("" if to else
             "ATENÇÃO: nenhum gestor cadastrado para este posto no Hesk "
             "(Configurações → Gestores dos postos). Este aviso foi só para a cópia.\n\n")
    linhas = [
        saud, "",
        (f"O relatório \"{card.title}\" do posto {posto} está sem anexo nos seguintes meses: "
         f"{meses_txt}." if plural else
         f"O relatório \"{card.title}\" do posto {posto} referente a {meses_txt} não foi anexado "
         f"até o prazo ({entries[0].due_on:%d/%m/%Y})."),
        "",
    ]
    for e in entries:
        atraso = (today_local() - e.due_on).days
        linhas.append(f"- {label(e.month)}: prazo {e.due_on:%d/%m/%Y}"
                      + (f" ({atraso} dias em atraso)" if atraso > 0 else " (vence hoje)"))
    linhas += [
        "",
        "Anexe cada arquivo na aba Anexos do card. Se o nome do arquivo trouxer o mês "
        "(ex.: \"Relatório CEDAE - Junho de 2026.pdf\") ele é creditado àquele mês; "
        "senão entra no mês pendente mais antigo. A cada anexo o Leonardo Pereira recebe "
        "o aviso com o resumo.",
        "",
        f"Abrir o card: {_card_link(card)}",
    ]
    _send_mail(to, subject, aviso + "\n".join(linhas), cc=[p["recipient_email"]])
    _log(card, None, (
        f"<p>Cobrança enviada: relatório sem anexo em <strong>{escape(', '.join(label(e.month) for e in entries))}</strong>"
        f" — para {escape(', '.join(nomes) or 'ninguém (sem gestores cadastrados no Hesk)')}"
        f" com cópia para {escape(p['recipient_email'] or '—')}.</p>"
    ))


# ---------------------------------------------------------------------------
# Painel do card (aba Mensal / chip)
# ---------------------------------------------------------------------------
def panel_context(card, today: date = None) -> dict:
    """Contexto da aba "Mensal". {} quando a coluna não tem a regra."""
    from boards.models import CardAttachment, MonthlyReportEntry

    rule = rule_for_card(card)
    if rule is None:
        return {}
    today = today or today_local()
    ensure_current(rule, card, today)
    entries = list(
        MonthlyReportEntry.objects.filter(card=card)
        .select_related("attachment", "attached_by", "accepted_by")
        .order_by("-month")
    )
    extra_ids = set()
    for e in entries:
        extra_ids.update(e.extra_attachment_ids or [])
    extras = {a.id: a for a in CardAttachment.objects.filter(id__in=extra_ids)} if extra_ids else {}
    for e in entries:
        e.extras = [extras[i] for i in (e.extra_attachment_ids or []) if i in extras]
        e.is_late = e.status in ("pending", "rejected") and today > e.due_on
    # "atual" = o mês em aberto MAIS ANTIGO (é nele que o próximo anexo entra)
    current = next((e for e in reversed(entries) if e.status in ("pending", "rejected", "validating")), None)
    if current is None:
        current = next((e for e in entries if e.month == month_first(today)), None)
    p = rule_params(rule)
    return {
        "rule": rule,
        "params": p,
        "entries": entries,
        "current": current,
        "gestores": responsaveis(rule),
        "posto": posto_nome(rule),
        "next_label": label(month_first(today)),
        "today": today,
    }


def chip_for_card(card, today: date = None):
    """{'text','tone'} para o card do quadro, ou None."""
    if card.column_id not in monthly_column_ids():
        return None
    from boards.models import MonthlyReportEntry
    today = today or today_local()
    e = (
        MonthlyReportEntry.objects.filter(card=card, status__in=["pending", "rejected", "validating"])
        .order_by("month").first()
    )
    if e is None:
        e = MonthlyReportEntry.objects.filter(card=card, month=month_first(today)).first()
        if e is None:
            return {"text": f"📎 falta {label(month_first(today))}", "tone": "warn"}
    if e.status == "delivered":
        return {"text": f"📎 {label(e.month)} ok", "tone": "ok"}
    if e.status == "validating":
        return {"text": f"📎 {label(e.month)} validando", "tone": "info"}
    if e.status == "rejected":
        return {"text": f"📎 {label(e.month)} reprovado", "tone": "late"}
    tone = "late" if today > e.due_on else "warn"
    return {"text": f"📎 falta {label(e.month)}", "tone": tone}


# ---------------------------------------------------------------------------
# Rollout / histórico (usado pelo comando setup_monthly_reports)
# ---------------------------------------------------------------------------
def seed_card(rule, card, today: date = None, actor=None) -> dict:
    """Monta o livro-razão a partir dos anexos existentes e ajusta o card.

    Meses antes do mês corrente: `delivered` (anexo mais antigo do mês) ou
    `skipped`. Mês corrente: `delivered` (rola a data) ou `pending`.
    Idempotente: não mexe em entradas já existentes."""
    from boards.models import CardAttachment, MonthlyReportEntry
    from boards.services.notifications import mark_card_undelivered

    today = today or today_local()
    cur = month_first(today)
    p = rule_params(rule)
    atts = list(
        CardAttachment.objects.filter(card=card).select_related("created_by").order_by("created_at")
    )
    by_month: dict = {}
    for a in atts:
        up = month_first(timezone.localtime(a.created_at).date())
        hint = month_from_filename(_display_name(a), today)
        # nome do arquivo manda, desde que não aponte para o futuro nem para
        # muito antes do upload (proteção contra "2025" em modelo reaproveitado)
        m = hint if (hint and hint <= up and add_months(hint, 3) >= up) else up
        by_month.setdefault(m, []).append(a)

    first = min(by_month) if by_month else cur
    # start_month explícito na regra manda; sem ele, histórico de no máximo 12 meses
    if (rule.params or {}).get("start_month"):
        first = max(first, start_month(rule))
    else:
        first = max(first, add_months(cur, -12))
    m = min(first, cur)
    created = 0
    while m <= cur:
        if not MonthlyReportEntry.objects.filter(card=card, month=m).exists():
            group = by_month.get(m) or []
            if group:
                a = group[0]
                MonthlyReportEntry.objects.create(
                    rule=rule, card=card, month=m, due_on=due_on(m, p["day"]),
                    status="delivered", attachment=a, attached_at=a.created_at,
                    attached_by=a.created_by, ai_status="off",
                    extra_attachment_ids=[x.id for x in group[1:]],
                )
            else:
                # mês sem relatório = PENDENTE (será cobrado), mesmo no passado
                MonthlyReportEntry.objects.create(
                    rule=rule, card=card, month=m, due_on=due_on(m, p["day"]),
                    status="pending", ai_status="off",
                )
            created += 1
        m = add_months(m, 1)

    cur_entry = MonthlyReportEntry.objects.get(card=card, month=cur)
    first_open = open_entries(card, cur).first()
    if first_open is None:
        nxt = ensure_entry(rule, card, add_months(cur, 1))
        new_due = nxt.due_on
    else:
        new_due = first_open.due_on
    pend = [label(e.month) for e in open_entries(card, cur)]
    mark_card_undelivered(card=card, clear_due=False)
    card.due_date = new_due
    card.save(update_fields=["due_date"])
    _log(card, actor, (
        f"<p>Automação de entrega mensal ativada. "
        + (f"Meses sem relatório: <strong>{escape(', '.join(pend))}</strong>." if pend
           else f"Relatório de <strong>{label(cur)}</strong> entregue.")
        + f" Data de entrega do card: {new_due:%d/%m/%Y}.</p>"
    ))
    return {"created": created, "current": cur_entry.status, "pending": pend, "due": new_due}
