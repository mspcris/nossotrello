from django.shortcuts import get_object_or_404, render
from .models import UserProfile

def view_profile(request, handle):
    profile = get_object_or_404(UserProfile, handle=handle)
    return render(request, "accounts/public_profile.html", {"profile": profile})
