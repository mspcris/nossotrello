#boards/views/__init__.py
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm
from django.core.cache import cache
from django.shortcuts import redirect, render

# Reexport dos seus módulos existentes (mantém compat com o projeto atual)
from .activity import *  # noqa
from .attachments import *  # noqa
from .boards import *  # noqa
from .cards import *  # noqa
from .checklists import *  # noqa
from .columns import *  # noqa
from .helpers import *  # noqa
from .legacy import *  # noqa
from .mentions import *  # noqa
from .account import *  # noqa
from .profiles import *  # noqa
from .modal_card_term import *  # noqa





class FirstLoginPasswordResetForm(PasswordResetForm):
    """
    Permite enviar e-mail de reset mesmo se o usuário ainda não tem senha utilizável
    (caso típico do "primeiro login" recém-criado).
    """
    def get_users(self, email):
        UserModel = get_user_model()
        email_field_name = getattr(UserModel, "EMAIL_FIELD", "email")

        users = UserModel._default_manager.filter(**{
            f"{email_field_name}__iexact": email,
            "is_active": True,
        })
        return (u for u in users)


def _is_allowed_institutional_email(email: str) -> bool:
    email = (email or "").strip().lower()
    if "@" not in email:
        return False
    domain = email.split("@", 1)[1]
    allowed = getattr(settings, "INSTITUTIONAL_EMAIL_DOMAINS", [])
    allowed = [d.strip().lower() for d in allowed if d and d.strip()]
    return domain in allowed


def _rate_limit_hit(email: str, ip: str) -> None:
    """
    Rate-limit: 5/min por e-mail e por IP.
    """
    email = (email or "").strip().lower()
    ip = (ip or "").strip().lower() or "unknown"

    for key in (f"first_login:email:{email}", f"first_login:ip:{ip}"):
        current = cache.get(key, 0) + 1
        cache.set(key, current, timeout=60)


def _can_send_now(email: str, ip: str) -> bool:
    email = (email or "").strip().lower()
    ip = (ip or "").strip().lower() or "unknown"
    e = cache.get(f"first_login:email:{email}", 0)
    i = cache.get(f"first_login:ip:{ip}", 0)
    return e <= 5 and i <= 5


def first_login(request):
    """
    GET: mostra tela "Primeiro login"
    POST: valida domínio, cria usuário se não existir, envia e-mail para definir senha.
    Mensagem sempre neutra (anti-enumeração).
    """
    if request.method == "GET":
        return render(request, "registration/first_login.html", {
            "allowed_domains": getattr(settings, "INSTITUTIONAL_EMAIL_DOMAINS", []),
        })

    email = (request.POST.get("email") or "").strip().lower()
    ip = request.META.get("REMOTE_ADDR", "")

    _rate_limit_hit(email=email, ip=ip)

    # Mensagem neutra (anti-enumeração)
    neutral_msg = "Se este e-mail estiver apto, enviaremos um link para você definir a senha."
    if not _is_allowed_institutional_email(email):
        messages.info(request, neutral_msg)
        return redirect("boards:first_login")

    UserModel = get_user_model()
    email_field_name = getattr(UserModel, "EMAIL_FIELD", "email")

    user = None
    if hasattr(UserModel, email_field_name):
        user = UserModel._default_manager.filter(**{f"{email_field_name}__iexact": email}).first()

    if user is None:
        username_field = getattr(UserModel, "USERNAME_FIELD", "username")

        create_kwargs = {username_field: email}

        # sempre tenta setar o campo de e-mail se existir
        if hasattr(UserModel, email_field_name):
            create_kwargs[email_field_name] = email

        user = UserModel._default_manager.create(**create_kwargs)
        user.set_unusable_password()
        user.save(update_fields=["password"])

    # Envia e-mail somente se rate-limit permitir (resposta continua neutra sempre)
    if _can_send_now(email=email, ip=ip):
        form = FirstLoginPasswordResetForm(data={"email": email})
        if form.is_valid():
            form.save(
                request=request,
                use_https=request.is_secure(),
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                email_template_name="registration/password_reset_email.txt",
                subject_template_name="registration/password_reset_subject.txt",
            )

    messages.info(request, neutral_msg)
    return redirect("boards:login")

from .search import board_search  # noqa
#END boards/views/__init__.py