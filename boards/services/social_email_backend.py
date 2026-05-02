"""
Backend SMTP exclusivo para a parte social (KingHost).

Por que existir, em vez de usar o EmailBackend padrão do Django:
- O KingHost serve certificados SSL do shared host real
  (ex.: smtp-sp217-108.kinghost.net), distintos do nome de marketing
  configurado em EMAIL_HOST (smtp.kinghost.net). Com a verificação
  de hostname padrão, qualquer envio falha com SSL_CERTIFICATE_VERIFY_FAILED.
  Aqui desligamos check_hostname mantendo a verificação de cadeia.
"""
from __future__ import annotations

import ssl

from django.core.mail.backends.smtp import EmailBackend
from django.utils.functional import cached_property


class KinghostSocialEmailBackend(EmailBackend):
    @cached_property
    def ssl_context(self):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        return ctx
