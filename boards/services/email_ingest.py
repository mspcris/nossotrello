# boards/services/email_ingest.py
"""
Sync de caixa de e-mail -> cards (feature "Criar Card From Email").

Suporta IMAP e POP3. Usado pelo command `sync_email_cards` (cron) e pelo
botão "Sincronizar agora".

Segurança: a senha fica criptografada (secret_crypto); só é decifrada aqui,
em memória, na hora de logar.
"""
import email
import imaplib
import logging
import poplib
from email.header import decode_header, make_header
from email.utils import parseaddr

from django.utils import timezone

from .secret_crypto import decrypt_secret

logger = logging.getLogger(__name__)

# trava de segurança: no máximo N cards por execução (evita enxurrada)
MAX_PER_SYNC = 50
# limite de UIDLs guardados p/ dedup no POP (bound de tamanho)
SEEN_CAP = 2000


def _decode(value):
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _extract_body(msg):
    """Texto simples do e-mail (prefere text/plain)."""
    parts = list(msg.walk()) if msg.is_multipart() else [msg]
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
    for part in parts:
        if part.get_content_type().startswith("text/"):
            try:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace").strip()
            except Exception:
                continue
    return ""


def _card_from_msg(config, msg):
    """Cria um Card a partir de uma mensagem de e-mail."""
    from boards.models import Card  # evita import circular

    subject = _decode(msg.get("Subject")) or "(sem assunto)"
    from_name, from_addr = parseaddr(msg.get("From") or "")
    date_str = _decode(msg.get("Date"))
    body = _extract_body(msg)

    desc = f"De: {from_name} <{from_addr}>\nData: {date_str}\n\n{body}".strip()
    Card.objects.create(
        column=config.target_column,
        title=subject[:255],
        description=desc,
        tags=(from_addr or from_name or "email")[:255],
        created_by=config.created_by,
    )


def _touch(config, **fields):
    config.last_sync_at = timezone.now()
    fields_to_save = list(fields.keys()) + ["last_sync_at"]
    for k, v in fields.items():
        setattr(config, k, v)
    config.save(update_fields=fields_to_save)


# ----------------------------------------------------------------------
# IMAP
# ----------------------------------------------------------------------
def _sync_imap(config, password):
    if config.use_ssl:
        conn = imaplib.IMAP4_SSL(config.imap_host, config.imap_port, timeout=20)
    else:
        conn = imaplib.IMAP4(config.imap_host, config.imap_port, timeout=20)
    try:
        conn.login(config.email_user, password)
        conn.select("INBOX")

        typ, data = conn.uid("search", None, "ALL")
        if typ != "OK":
            raise RuntimeError("Falha no SEARCH IMAP.")
        uids = data[0].split()
        if not uids:
            _touch(config, last_error="")
            return 0, None

        last_uid = int(config.last_uid) if config.last_uid.isdigit() else 0
        if last_uid == 0:
            # baseline: não importa histórico
            _touch(config, last_uid=uids[-1].decode(), last_error="")
            return 0, None

        new_uids = [u for u in uids if int(u) > last_uid][:MAX_PER_SYNC]
        created = 0
        max_seen = last_uid
        for u in new_uids:
            typ, msg_data = conn.uid("fetch", u, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            _card_from_msg(config, email.message_from_bytes(msg_data[0][1]))
            created += 1
            max_seen = max(max_seen, int(u))

        _touch(config, last_uid=str(max_seen), last_error="")
        return created, None
    finally:
        try:
            conn.logout()
        except Exception:
            pass


# ----------------------------------------------------------------------
# POP3
# ----------------------------------------------------------------------
def _sync_pop(config, password):
    if config.use_ssl:
        conn = poplib.POP3_SSL(config.imap_host, config.imap_port, timeout=20)
    else:
        conn = poplib.POP3(config.imap_host, config.imap_port, timeout=20)
    try:
        conn.user(config.email_user)
        conn.pass_(password)

        # UIDL: lista de "msg_num uidl"
        _resp, items, _octets = conn.uidl()
        pairs = []
        for it in items:
            parts = it.decode(errors="replace").split()
            if len(parts) >= 2:
                pairs.append((int(parts[0]), parts[1]))

        if not pairs:
            _touch(config, last_error="")
            return 0, None

        first_run = not config.last_sync_at
        if first_run:
            # baseline: marca tudo como visto, sem criar cards
            _touch(config, seen_uids=[u for _, u in pairs][-SEEN_CAP:], last_error="")
            return 0, None

        seen = set(config.seen_uids or [])
        new_pairs = [(n, u) for (n, u) in pairs if u not in seen][:MAX_PER_SYNC]
        created = 0
        for msg_num, uidl in new_pairs:
            _resp, lines, _octets = conn.retr(msg_num)
            raw = b"\r\n".join(lines)
            _card_from_msg(config, email.message_from_bytes(raw))
            seen.add(uidl)
            created += 1

        # mantém só os UIDLs atuais (+ os novos), limitado
        current = [u for _, u in pairs]
        merged = [u for u in current if u in seen][-SEEN_CAP:]
        _touch(config, seen_uids=merged, last_error="")
        return created, None
    finally:
        try:
            conn.quit()
        except Exception:
            pass


# ----------------------------------------------------------------------
# dispatcher
# ----------------------------------------------------------------------
def sync_one(config):
    """
    Cria cards para e-mails novos na coluna-alvo. Retorna (created:int, error:str|None).
    1ª execução faz BASELINE (não importa histórico).
    """
    if not config.target_column or config.target_column.is_deleted:
        return 0, "Coluna-alvo inexistente. Reconfigure a coluna."
    if not config.password_encrypted:
        return 0, "Senha não configurada."

    try:
        password = decrypt_secret(bytes(config.password_encrypted))
    except Exception as e:
        return 0, f"Falha ao decifrar a senha: {e}"

    try:
        if config.protocol == "pop":
            created, err = _sync_pop(config, password)
        else:
            created, err = _sync_imap(config, password)
    except Exception as e:
        logger.exception("email ingest sync failed board=%s", config.board_id)
        _touch(config, last_error=str(e))
        return 0, str(e)

    # Criou cards? Bump na versão do board -> dispara o signal board.invalidated
    # (post_save de Board) -> a página aberta re-renderiza as colunas via poll,
    # sem F5. Mesmo mecanismo das operações de card pela UI.
    if created and not err:
        try:
            board = config.board
            board.version = (board.version or 0) + 1
            board.save(update_fields=["version"])
        except Exception:
            logger.debug("bump board version (email ingest) falhou", exc_info=True)

    return created, err
