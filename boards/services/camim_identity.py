"""
Resolução de identidade do IDCamim (OAuth) para User local.

Regra: o `sub` do IDCamim é o identificador estável e deve ser a chave
primária do vínculo. Email muda (o Lincoln já comprovou); sub não.

Fluxo:
  1. Se há UserProfile.camim_sub == sub → usa esse user, atualiza email
     e nome se mudaram no IDCamim.
  2. Senão, tenta casar por email__iexact (compat com users pré-sub):
     encontrou → grava o sub nesse user e segue.
  3. Senão, cria um novo user + profile e grava o sub.

Edge cases:
  - Email "órfão" de um sub: não acontece se sub é sempre enviado e
    gravamos na primeira oportunidade.
  - Dois users com mesmo email (histórico): pega o de menor id (mesmo
    critério que a lógica anterior usava).
"""

import logging
from urllib.parse import urlparse

import requests
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import transaction

logger = logging.getLogger(__name__)

User = get_user_model()

# Extensões derivadas do content-type ao importar a foto do IDCamim
_IMAGE_EXT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}
_MAX_AVATAR_BYTES = 5 * 1024 * 1024  # mesmo limite do upload manual (account.py)


def resolve_or_create_camim_user(*, sub: str, email: str,
                                 first_name: str = "", last_name: str = ""):
    """
    Retorna o User correspondente ao sub do IDCamim. Cria se não existir.
    Grava o sub na primeira vez que um user pré-existente aparece aqui.

    Campos atualizados no user quando sub já existe e algo mudou:
      - email (se o IDCamim retornou um novo)
      - first_name / last_name (se vieram preenchidos e diferentes)
    """
    from boards.models import UserProfile

    sub = (sub or "").strip()
    email = (email or "").strip().lower()

    # 1) Busca por sub
    if sub:
        profile = (
            UserProfile.objects
            .select_related("user")
            .filter(camim_sub=sub)
            .first()
        )
        if profile is not None:
            user = profile.user
            _sync_user_fields(user, email=email, first_name=first_name, last_name=last_name)
            return user

    # 2) Fallback: casar por email (users legados sem sub gravado)
    if email:
        user = User.objects.filter(email__iexact=email).order_by("id").first()
        if user is not None:
            _sync_user_fields(user, email=email, first_name=first_name, last_name=last_name)
            if sub:
                _set_camim_sub(user, sub)
            return user

    # 3) Novo user
    return _create_user_with_sub(
        sub=sub, email=email, first_name=first_name, last_name=last_name
    )


def maybe_import_camim_avatar(user, picture_url: str, access_token: str = "") -> bool:
    """
    Puxa a foto do IDCamim (`picture` do /me) para o perfil local — só leitura,
    nunca escreve de volta no IDCamim.

    Regra (decidida com o Cristiano): só importa quando o usuário NÃO tem uma
    foto que ele mesmo colocou, ou seja, sem upload (`avatar`) E sem preset
    (`avatar_choice`). Preset escolhido conta como "foto que ele colocou".

    Qualquer falha (download, content-type, tamanho) é engolida e logada — nunca
    pode quebrar o login.

    Retorna True se importou a foto.
    """
    from boards.models import UserProfile

    picture_url = (picture_url or "").strip()
    if not picture_url:
        return False

    # IDCamim pode devolver caminho relativo ("/uploads/x.png") em vez de URL absoluta
    if picture_url.startswith("/"):
        picture_url = "https://auth.camim.com.br" + picture_url

    profile, _ = UserProfile.objects.get_or_create(user=user)

    # Já tem foto que ele colocou (upload ou preset) → não mexe
    if profile.avatar or profile.avatar_choice:
        return False

    try:
        # Só manda o Bearer se a foto está no próprio domínio do Camim
        # (evita vazar o token para um CDN/terceiro).
        headers = {}
        if access_token and urlparse(picture_url).netloc.endswith("camim.com.br"):
            headers["Authorization"] = f"Bearer {access_token}"

        resp = requests.get(picture_url, headers=headers, timeout=10, verify=False)
        resp.raise_for_status()

        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if not ctype.startswith("image/"):
            logger.warning("IDCamim picture não é imagem (content-type=%s) para %s", ctype, user.pk)
            return False

        content = resp.content
        if len(content) > _MAX_AVATAR_BYTES:
            logger.warning("IDCamim picture maior que 5MB (%s bytes) para %s", len(content), user.pk)
            return False
    except Exception as exc:
        logger.warning("Falha ao importar foto do IDCamim para %s: %s", user.pk, exc)
        return False

    ext = _IMAGE_EXT.get(ctype, "jpg")
    profile.avatar.save(f"camim_{user.pk}.{ext}", ContentFile(content), save=False)
    profile.save(update_fields=["avatar"])
    return True


def maybe_import_camim_phone(user, phone_number: str) -> bool:
    """
    Puxa o telefone do IDCamim (`phone_number` do /me, scope `phone`) para o
    perfil local — só leitura, nunca escreve de volta no IDCamim.

    Mesma regra da foto: só preenche quando o usuário ainda NÃO colocou um
    telefone próprio. Não mexe na flag `share_telefone` (preferência do user).

    Retorna True se importou o telefone.
    """
    from boards.models import UserProfile

    phone_number = (phone_number or "").strip()
    if not phone_number:
        return False

    profile, _ = UserProfile.objects.get_or_create(user=user)

    # Já tem telefone que ele colocou → não sobrescreve
    if (profile.telefone or "").strip():
        return False

    profile.telefone = phone_number[:30]  # max_length do campo
    profile.save(update_fields=["telefone"])
    return True


def _sync_user_fields(user, *, email, first_name, last_name):
    fields = []
    if email and (user.email or "").lower() != email:
        user.email = email
        fields.append("email")
    if first_name and user.first_name != first_name:
        user.first_name = first_name
        fields.append("first_name")
    if last_name and user.last_name != last_name:
        user.last_name = last_name
        fields.append("last_name")
    if fields:
        user.save(update_fields=fields)


def _set_camim_sub(user, sub: str):
    from boards.models import UserProfile
    profile, _ = UserProfile.objects.get_or_create(user=user)
    if profile.camim_sub != sub:
        profile.camim_sub = sub
        profile.save(update_fields=["camim_sub"])


def _create_user_with_sub(*, sub, email, first_name, last_name):
    from boards.models import UserProfile

    # Username baseado no prefixo do email, garantindo unicidade
    base_username = email.split("@")[0] if email else (sub[:20] or "user")
    username = base_username
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f"{base_username}{counter}"
        counter += 1

    with transaction.atomic():
        user = User.objects.create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=None,  # só entra via IDCamim
        )
        if sub:
            UserProfile.objects.get_or_create(user=user, defaults={"camim_sub": sub})
    return user
