from django.shortcuts import render

def portal(request):
    return render(request, "tracktime/portal.html")

def card_tracktime_panel(request, card_id):
    return render(
        request,
        "tracktime/card_tracktime_panel.html",
        {"card_id": card_id},
    )

def card_tracktime_manual(request, card_id):
    return render(
        request,
        "tracktime/card_tracktime_manual.html",
        {"card_id": card_id},
    )
