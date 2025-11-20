from django.urls import path
from . import views

app_name = "boards"

urlpatterns = [
    path("", views.index, name="boards_index"),

    path("board/<int:board_id>/", views.board_detail, name="board_detail"),
    path("board/<int:board_id>/add_column/", views.add_column, name="add_column"),
    path("board/<int:board_id>/image/", views.update_board_image, name="update_board_image"),
    path("board/<int:board_id>/image/remove/", views.remove_board_image, name="remove_board_image"),

    path("board/add/", views.add_board, name="add_board"),

    path("column/<int:column_id>/add_card/", views.add_card, name="add_card"),
    path("column/<int:column_id>/delete/", views.delete_column, name="delete_column"),
    path("column/<int:column_id>/theme/", views.set_column_theme, name="set_column_theme"),

    path("card/<int:card_id>/edit/", views.edit_card, name="edit_card"),
    path("card/<int:card_id>/modal/", views.card_modal, name="card_modal"),
    path("card/<int:card_id>/update/", views.update_card, name="update_card"),
    path("card/<int:card_id>/delete/", views.delete_card, name="delete_card"),

    path("move-card/", views.move_card, name="move_card"),
    path("card/<int:card_id>/delete-attachment/", views.delete_attachment, name="delete_attachment"),
    path("card/<int:card_id>/snippet/", views.card_snippet, name="card_snippet"),
    path("card/<int:card_id>/remove_tag/", views.remove_tag, name="remove_tag"),
    path("board/<int:board_id>/rename/", views.rename_board, name="rename_board"),

]
