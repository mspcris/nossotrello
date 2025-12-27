# boards/views/polling.py
@login_required
def board_poll(request, board_id):
    board = get_object_or_404(Board, id=board_id)

    # segurança: permissão
    if not board.user_can_view(request.user):
        return JsonResponse({"error": "forbidden"}, status=403)

    # versão que o cliente já tem
    client_version = int(request.GET.get("v", 0))

    if board.version == client_version:
        return JsonResponse({
            "version": board.version,
            "changed": False,
        })

    columns = (
        Column.objects
        .filter(board=board)
        .prefetch_related("cards")
        .order_by("position")
    )

    html = render_to_string(
        "boards/partials/columns_list.html",
        {"columns": columns},
        request=request,
    )

    response = JsonResponse({
        "version": board.version,
        "changed": True,
        "html": html,
    })

    response["Cache-Control"] = "no-store"
    return response
#END polling.y