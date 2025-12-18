# boards/views/legacy.py

from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST


@require_POST
def set_card_cover(request, card_id):
    return HttpResponse("Not implemented", status=501)


@require_POST
def remove_card_cover(request, card_id):
    return HttpResponse("Not implemented", status=501)
