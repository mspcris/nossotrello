import random
from django.contrib.auth import get_user_model
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


@receiver(post_save, sender=get_user_model())
def ensure_profile_on_user_create(sender, instance, created, **kwargs):
    if not created:
        return

    prof, _ = UserProfile.objects.get_or_create(user=instance)

    # se ainda não tem avatar uploadado e nem preset escolhido, define um preset
    if not prof.avatar and not prof.avatar_choice:
        prof.avatar_choice = random.choice(DEFAULT_AVATARS)
        prof.save(update_fields=["avatar_choice"])
