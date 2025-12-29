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
