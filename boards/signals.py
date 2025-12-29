# boards/signals.py
import random
import re

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile

DEFAULT_AVATARS = [
    "avatar1.jpeg",
    "avatar2.png",
    "avatar3.png",
    "avatar4.png",
    "avatar5.png",
    "avatar6.png",
    "avatar7.png",
    "avatar8.png",
    "avatar9.png",
    "avatar10.png",
    "avatar11.png",
]


def _sanitize_handle_base(text: str) -> str:
    """
    Gera uma base segura para handle:
    - usa apenas [a-zA-Z0-9_]
    - cai para 'user' se ficar vazio
    """
    t = (text or "").strip()
    t = re.sub(r"[^a-zA-Z0-9_]+", "", t)
    return t or "user"


def _default_display_name_from_email(email: str) -> str:
    """
    Nome amigável = parte antes do @.
    """
    e = (email or "").strip()
    local = e.split("@", 1)[0] if "@" in e else e
    return (local or "usuario").strip() or "usuario"


def _generate_unique_handle(email: str, *, max_attempts: int = 9999) -> str:
    """
    Handle = 5 primeiros caracteres do email (antes do @) + contagem 01, 02, 03...
    Garantindo unicidade em UserProfile.handle.
    """
    local = _default_display_name_from_email(email)
    base_raw = local[:5]  # regra acordada
    base = _sanitize_handle_base(base_raw)

    # Tenta 01..N; mantém o base dentro de um tamanho seguro
    # (se o campo handle for curto, evitar estourar)
    # Ajuste conservador: reserva até 4 chars para sufixo (ex: 0001) se precisar.
    base = base[:20]

    for i in range(1, max_attempts + 1):
        suffix = f"{i:02d}" if i < 100 else str(i)
        candidate = f"{base}{suffix}"

        # Se ainda assim ficar grande, corta o base e tenta de novo
        if len(candidate) > 24:
            overflow = len(candidate) - 24
            base_cut = base[:-overflow] if overflow < len(base) else "user"
            candidate = f"{base_cut}{suffix}"

        if not UserProfile.objects.filter(handle=candidate).exists():
            return candidate

    # fallback extremo (não deve acontecer)
    return f"{base}01"


@receiver(post_save, sender=get_user_model())
def ensure_profile_on_user_create(sender, instance, created, **kwargs):
    if not created:
        return

    # Melhor esforço com atomic + retry simples para corrida de unicidade no handle
    for _ in range(3):
        try:
            with transaction.atomic():
                prof, _created_prof = UserProfile.objects.get_or_create(user=instance)

                changed_fields = []

                # 1) display_name default (antes do @)
                if not (prof.display_name or "").strip():
                    prof.display_name = _default_display_name_from_email(getattr(instance, "email", "") or "")
                    changed_fields.append("display_name")

                # 2) handle default (5 primeiros + 01..)
                if not (prof.handle or "").strip():
                    prof.handle = _generate_unique_handle(getattr(instance, "email", "") or "")
                    changed_fields.append("handle")

                # 3) avatar preset (se não tiver upload nem escolha)
                if not prof.avatar and not prof.avatar_choice:
                    prof.avatar_choice = random.choice(DEFAULT_AVATARS)
                    changed_fields.append("avatar_choice")

                if changed_fields:
                    prof.save(update_fields=changed_fields)

            break

        except IntegrityError:
            # colisão rara de handle em concorrência; tenta de novo
            continue
