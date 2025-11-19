from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="boards_index"),
    path("board/<int:board_id>/", views.board_detail, name="board_detail"),
    path("board/<int:board_id>/add_column/", views.add_column, name="add_column"),
    path("column/<int:column_id>/add_card/", views.add_card, name="add_card"),
    path("move-card/", views.move_card, name="move_card"),
    path("board/add/", views.add_board, name="add_board"),
    path("card/<int:card_id>/edit/", views.edit_card, name="edit_card"),
    path("card/<int:card_id>/modal/", views.card_modal, name="card_modal"),
    path("card/<int:card_id>/update/", views.update_card, name="update_card"),
]
