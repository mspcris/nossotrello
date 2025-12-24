# boards/context_processors.py
def user_profile_context(request):
    user = getattr(request, "user", None)
    avatar_url = None

    if user and getattr(user, "is_authenticated", False):
        try:
            profile = user.profile  # related_name="profile"
            if profile and getattr(profile, "avatar", None):
                avatar = profile.avatar
                if getattr(avatar, "url", None):
                    avatar_url = avatar.url
        except Exception:
            avatar_url = None

    return {"user_avatar_url": avatar_url}
