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

from django.contrib.auth import get_user_model
from django.db import transaction

User = get_user_model()


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
