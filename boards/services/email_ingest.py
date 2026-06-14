# boards/services/email_ingest.py
"""
Sync de caixa IMAP -> cards (feature "Criar Card From Email").

Usado pelo management command `sync_email_cards` (cron) e pelo botão
"Sincronizar agora" do modal de configuração.

Segurança: a senha fica criptografada (secret_crypto); só é decifrada aqui,
em memória, na hora de logar no IMAP.
"""
import email
import imaplib
import logging
from email.header import decode_header, make_header
from email.utils import parseaddr

from django.utils import timezone

from .secret_crypto import decrypt_secret

logger = logging.getLogger(__name__)

# trava de segurança: no máximo N cards por execução (evita enxurrada)
MAX_PER_SYNC = 50


def _decode(value):
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _extract_body(msg):
    """Texto simples do e-mail (prefere text/plain)."""
    parts = msg.walk() if msg.is_multipart() else [msg]
    # 1ª passada: text/plain que não seja anexo
    for part in parts:
        if part.get_content_type() == "text/plain" and "attachment" not in str(
            part.get("Content-Disposition") or ""
        ):
            try:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace").strip()
            except Exception:
                continue
    # fallback: qualquer text/*
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        if part.get_content_type().startswith("text/"):
            try:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace").strip()
            except Exception:
                continue
    return ""


def sync_one(config):
    """
    Cria cards para e-mails novos da caixa configurada na coluna-alvo.
    Retorna (created:int, error:str|None).

    1ª execução faz BASELINE: guarda o maior UID atual e NÃO cria cards de
    e-mails já existentes — só o que chegar depois vira card.
    """
    from boards.models import Card  # evita import circular

    if not config.target_column or config.target_column.is_deleted:
        return 0, "Coluna-alvo inexistente. Reconfigure a coluna."
    if not config.password_encrypted:
        return 0, "Senha não configurada."

    try:
        password = decrypt_secret(bytes(config.password_encrypted))
    except Exception as e:
        return 0, f"Falha ao decifrar a senha: {e}"

    created = 0
    conn = None
    try:
        if config.use_ssl:
            conn = imaplib.IMAP4_SSL(config.imap_host, config.imap_port, timeout=20)
        else:
            conn = imaplib.IMAP4(config.imap_host, config.imap_port, timeout=20)
        conn.login(config.email_user, password)
        conn.select("INBOX")

        typ, data = conn.uid("search", None, "ALL")
        if typ != "OK":
            raise RuntimeError("Falha no SEARCH IMAP.")
        uids = data[0].split()

        if not uids:
            config.last_sync_at = timezone.now()
            config.last_error = ""
            config.save(update_fields=["last_sync_at", "last_error"])
            return 0, None

        last_uid = int(config.last_uid) if config.last_uid.isdigit() else 0

        if last_uid == 0:
            # baseline: não importa histórico
            config.last_uid = uids[-1].decode()
            config.last_sync_at = timezone.now()
            config.last_error = ""
            config.save(update_fields=["last_uid", "last_sync_at", "last_error"])
            return 0, None

        new_uids = [u for u in uids if int(u) > last_uid][:MAX_PER_SYNC]
        max_seen = last_uid
        for u in new_uids:
            typ, msg_data = conn.uid("fetch", u, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            subject = _decode(msg.get("Subject")) or "(sem assunto)"
            from_name, from_addr = parseaddr(msg.get("From") or "")
            date_str = _decode(msg.get("Date"))
            body = _extract_body(msg)

            desc = (
                f"De: {from_name} <{from_addr}>\n"
                f"Data: {date_str}\n\n{body}"
            ).strip()

            Card.objects.create(
                column=config.target_column,
                title=subject[:255],
                description=desc,
                tags=(from_addr or from_name or "email")[:255],
                created_by=config.created_by,
            )
            created += 1
            max_seen = max(max_seen, int(u))

        config.last_uid = str(max_seen)
        config.last_sync_at = timezone.now()
        config.last_error = ""
        config.save(update_fields=["last_uid", "last_sync_at", "last_error"])
        return created, None

    except Exception as e:
        logger.exception("email ingest sync failed board=%s", config.board_id)
        config.last_error = str(e)
        config.last_sync_at = timezone.now()
        config.save(update_fields=["last_error", "last_sync_at"])
        return created, str(e)
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass
