from django.urls import path
from . import views

app_name = "boards"

# ============================================================
# URLS DO APP BOARDS — ORGANIZADAS E COMENTADAS
# ============================================================
urlpatterns = [
    # ---------------------- HOME ----------------------
    path("", views.index, name="boards_index"),


    # ---------------------- LOGIN ----------------------
    path("users/create/", views.create_user, name="create_user"),


    # ---------------------- BOARD ----------------------
    path("board/<int:board_id>/", views.board_detail, name="board_detail"),
    path("board/<int:board_id>/share/", views.board_share, name="board_share"),
    path("board/<int:board_id>/share/remove/<int:user_id>/", views.board_share_remove, name="board_share_remove"),
    path("board/<int:board_id>/add_column/", views.add_column, name="add_column"),

    # imagem principal do board
    path("board/<int:board_id>/image/", views.update_board_image, name="update_board_image"),
    path("board/<int:board_id>/image/remove/", views.remove_board_image, name="remove_board_image"),

    # criar board
    path("board/add/", views.add_board, name="add_board"),

    # renomear board
    path("board/<int:board_id>/rename/", views.rename_board, name="rename_board"),

    # wallpaper do board
    path("board/<int:board_id>/wallpaper/", views.update_board_wallpaper, name="update_board_wallpaper"),
    path("board/<int:board_id>/wallpaper/remove/", views.remove_board_wallpaper, name="remove_board_wallpaper"),
    path("board/<int:board_id>/wallpaper.css", views.board_wallpaper_css, name="board_wallpaper_css"),

    # ---------------------- HOME WALLPAPER ----------------------
    path("home/wallpaper/", views.update_home_wallpaper, name="update_home_wallpaper"),
    path("home/wallpaper/remove/", views.remove_home_wallpaper, name="remove_home_wallpaper"),
    path("home/wallpaper.css", views.home_wallpaper_css, name="home_wallpaper_css"),

    # ---------------------- COLUMN ----------------------
    path("column/<int:column_id>/add_card/", views.add_card, name="add_card"),
    path("column/<int:column_id>/delete/", views.column_delete, name="column_delete"),
    path("column/<int:column_id>/delete/", views.delete_column, name="delete_column"),
    path("column/<int:column_id>/theme/", views.set_column_theme, name="set_column_theme"),
    path("column/<int:column_id>/rename/", views.rename_column, name="rename_column"),

    # ---------------------- CARD ----------------------
    path("card/<int:card_id>/edit/", views.edit_card, name="edit_card"),
    path("card/<int:card_id>/modal/", views.card_modal, name="card_modal"),
    path("card/<int:card_id>/update/", views.update_card, name="update_card"),
    path("card/<int:card_id>/delete/", views.delete_card, name="delete_card"),
    path("card/<int:card_id>/delete-attachment/", views.delete_attachment, name="delete_attachment"),
    path("card/<int:card_id>/snippet/", views.card_snippet, name="card_snippet"),
    path("card/<int:card_id>/remove_tag/", views.remove_tag, name="remove_tag"),

    # arrastar/mover card
    path("move-card/", views.move_card, name="move_card"),

    # atividades (Quill)
    path("card/<int:card_id>/activity/add/", views.add_activity, name="add_activity"),
    path("quill/upload/", views.quill_upload, name="quill_upload"),

    # anexos múltiplos
    path("card/<int:card_id>/attachments/add/", views.add_attachment, name="add_attachment"),

    # ---------------------- CHECKLISTS (múltiplos por card) ----------------------

    # CRUD do checklist
    path("card/<int:card_id>/checklist/add/", views.checklist_add, name="checklist_add"),
    path("checklist/<int:checklist_id>/rename/", views.checklist_rename, name="checklist_rename"),
    path("checklist/<int:checklist_id>/delete/", views.checklist_delete, name="checklist_delete"),
    path("checklist/<int:checklist_id>/move/", views.checklist_move, name="checklist_move"),

    # itens do checklist
    path("checklist/<int:checklist_id>/item/add/", views.checklist_add_item, name="checklist_add_item"),
    path("checklist/item/<int:item_id>/toggle/", views.checklist_toggle_item, name="checklist_toggle_item"),
    path("checklist/item/<int:item_id>/delete/", views.checklist_delete_item, name="checklist_delete_item"),
    path("checklist/item/<int:item_id>/update/", views.checklist_update_item, name="checklist_update_item"),

    # mover itens
    path(
        "checklist/item/<int:item_id>/move-up/", views.checklist_move_up, name="checklist_move_up",),
    path("checklist/item/<int:item_id>/move-down/", views.checklist_move_down, name="checklist_move_down",),
    path("board/<int:board_id>/delete/", views.delete_board, name="delete_board"),


]
