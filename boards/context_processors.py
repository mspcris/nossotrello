# boards/context_processors.py
from django.templatetags.static import static as static_url


def user_profile_context(request):
    user = getattr(request, "user", None)
    avatar_url = None

    if user and getattr(user, "is_authenticated", False):
        try:
            profile = getattr(user, "profile", None)

            # 1) Upload tem prioridade
            if profile and getattr(profile, "avatar", None):
                avatar = profile.avatar
                if getattr(avatar, "url", None):
                    avatar_url = avatar.url

            # 2) Se não tem upload, usa preset
            if not avatar_url and profile and getattr(profile, "avatar_choice", ""):
                avatar_url = static_url(f"images/avatar/{profile.avatar_choice}")

        except Exception:
            avatar_url = None

    return {"user_avatar_url": avatar_url}


def brand_context(request):
    """
    Decide qual marca mostrar no header com base no domínio do e-mail do usuário.
    - @egidesaude.com.br  -> Égide (logo sem texto)
    - @camim.com.br / @clinicacamim.com.br -> CAMIM (logo + texto)
    """
    email = ""
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        email = (getattr(user, "email", "") or "").strip().lower()

    # Defaults (CAMIM)
    brand = {
        "brand_key": "camim",
        "brand_name": "CAMIM",
        "brand_logo": "images/logo-camim.png",
        "brand_show_text": True,
    }

    if email.endswith("@egidesaude.com.br"):
        brand = {
            "brand_key": "egide",
            "brand_name": "Égide Saúde e Benefícios",
            "brand_logo": "images/egide-logo-verde.svg",  # ajuste se o nome real for outro
            "brand_show_text": False,  # Égide: sem texto ao lado
        }

    return brand
#END boards/context_processors.py