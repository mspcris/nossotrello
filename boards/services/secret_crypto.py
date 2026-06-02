# boards/services/secret_crypto.py
"""
Criptografia simétrica (Fernet) para os snippets/segredos de card.

O conteúdo (ex.: um `curl` com chave de API) NUNCA é gravado em claro no banco
— guardamos só o ciphertext em `CardSecret.ciphertext`. Isso protege dumps do
banco e os backups do RDS.

Chave-mestra:
- `settings.CARD_SECRET_KEY` (uma ou mais chaves Fernet separadas por vírgula —
  a primeira criptografa, todas descriptografam, permitindo rotação).
- Se ausente, deriva-se determinísticamente de `DJANGO_SECRET_KEY` apenas para
  não travar dev/HML. Em produção, defina `CARD_SECRET_KEY` e NÃO rotacione
  `DJANGO_SECRET_KEY` sem antes migrar os segredos.

Gerar uma chave:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import base64
import hashlib
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, MultiFernet, InvalidToken
from django.conf import settings

logger = logging.getLogger(__name__)


class SecretCryptoError(Exception):
    """Falha de criptografia/descriptografia de segredo de card."""


def _derive_key_from(secret: str) -> bytes:
    digest = hashlib.sha256((secret or "").encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=1)
def _fernet() -> MultiFernet:
    raw = (getattr(settings, "CARD_SECRET_KEY", "") or "").strip()
    keys = []

    if raw:
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                keys.append(Fernet(part.encode("utf-8")))
            except Exception as e:  # chave malformada
                raise SecretCryptoError(
                    "CARD_SECRET_KEY inválida — gere com Fernet.generate_key()."
                ) from e

    if not keys:
        logger.warning(
            "CARD_SECRET_KEY não definida; derivando chave de DJANGO_SECRET_KEY. "
            "Defina CARD_SECRET_KEY em produção e não rotacione DJANGO_SECRET_KEY "
            "sem migrar os segredos de card."
        )
        keys.append(Fernet(_derive_key_from(settings.SECRET_KEY)))

    return MultiFernet(keys)


def encrypt_secret(plaintext: str) -> bytes:
    """Retorna o token Fernet (bytes) pronto pra gravar em BinaryField."""
    if plaintext is None:
        plaintext = ""
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_secret(token) -> str:
    """Recebe o ciphertext (bytes/memoryview/str) e devolve o texto original."""
    if token is None:
        raise SecretCryptoError("Segredo vazio.")
    if isinstance(token, memoryview):
        token = token.tobytes()
    if isinstance(token, str):
        token = token.encode("utf-8")
    try:
        return _fernet().decrypt(token).decode("utf-8")
    except InvalidToken as e:
        raise SecretCryptoError(
            "Não foi possível descriptografar (chave incorreta ou token corrompido)."
        ) from e
