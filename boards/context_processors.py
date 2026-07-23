# boards/context_processors.py
from django.templatetags.static import static as static_url


def user_profile_context(request):
    user = getattr(request, "user", None)
    avatar_url = None

    if user and getattr(user, "is_authenticated", False):
        try:
            # Ordem (upload > IDCamim > preset) em UserProfile.avatar_url.
            profile = getattr(user, "profile", None)
            if profile:
                avatar_url = profile.avatar_url or None
        except Exception:
            avatar_url = None

    return {"user_avatar_url": avatar_url}


from django.templatetags.static import static as static_url

def brand_context(request):
    """
    Decide qual marca mostrar no header com base no e-mail do usuário.
    - @egidesaude.com.br  -> Égide (logo)
    - @camim.com.br / @clinicacamim.com.br -> CAMIM (logo)
    """
    user = getattr(request, "user", None)

    # pega do campo email; se vier vazio, usa username (muito comum em setups onde username = email)
    email = ""
    if user and getattr(user, "is_authenticated", False):
        email = (getattr(user, "email", "") or "").strip().lower()
        if not email:
            email = (getattr(user, "get_username", lambda: "")() or "").strip().lower()

    # default: CAMIM
    brand = {
        "brand_key": "camim",
        "brand_name": "CAMIM",
        "brand_logo": "images/logo-camim.png",
        "brand_show_text": False,  # você disse que vai remover o texto
    }

    if email.endswith("@egidesaude.com.br"):
        brand = {
            "brand_key": "egide",
            "brand_name": "Égide Saúde e Benefícios",
            "brand_logo": "images/egide-logo-verde.png",
            "brand_show_text": False,
        }

    return brand


from .models import UserProfile

def user_profile(request):
    if not request.user.is_authenticated:
        return {}
    prof, _ = UserProfile.objects.get_or_create(user=request.user)
    return {"profile": prof}


from .models import WhatsNewItem

def whats_new_context(request):
    user = getattr(request, "user", None)
    if not (user and getattr(user, "is_authenticated", False)):
        return {"whats_new_unseen": 0}
    try:
        prof, _ = UserProfile.objects.get_or_create(user=user)
        qs = WhatsNewItem.objects.filter(is_published=True)
        if prof.last_whatsnew_seen_at:
            qs = qs.filter(published_at__gt=prof.last_whatsnew_seen_at)
        count = qs.count()
    except Exception:
        count = 0
    return {"whats_new_unseen": count}

#END boards/context_processors.py