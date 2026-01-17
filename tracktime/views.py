from django.shortcuts import render

# Create your views here.
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def portal(request):
    return render(request, "tracktime/portal.html")
