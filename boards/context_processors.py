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


from django.core.cache import cache

from .models import WhatsNewItem

WHATSNEW_CACHE_TTL = 300


def whats_new_cache_key(user_id) -> str:
    return f"whatsnew_unseen:{user_id}"


def whats_new_context(request):
    """Badge "Novidades não vistas" do header.

    Rodava um get_or_create + COUNT em TODO render de página. Agora fica em
    cache por 5 min por usuário; whats_new_mark_seen invalida ao abrir o painel.
    """
    user = getattr(request, "user", None)
    if not (user and getattr(user, "is_authenticated", False)):
        return {"whats_new_unseen": 0}
    key = whats_new_cache_key(user.pk)
    try:
        count = cache.get(key)
    except Exception:
        count = None
    if count is None:
        try:
            prof = getattr(user, "profile", None)
            if prof is None:
                prof, _ = UserProfile.objects.get_or_create(user=user)
            qs = WhatsNewItem.objects.filter(is_published=True)
            if prof.last_whatsnew_seen_at:
                qs = qs.filter(published_at__gt=prof.last_whatsnew_seen_at)
            count = qs.count()
        except Exception:
            count = 0
        try:
            cache.set(key, count, WHATSNEW_CACHE_TTL)
        except Exception:
            pass
    return {"whats_new_unseen": count}

#END boards/context_processors.py