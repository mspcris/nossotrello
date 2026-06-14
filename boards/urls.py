# boards/urls.py
"""
URLs do app boards — versão "limpa" (imports explícitos por módulo).

Objetivo:
- Remover dependência de reexport via boards/views/__init__.py (import *)
- Evitar colisão de nomes e AttributeError em runtime
- Manter os mesmos names (compatibilidade com templates/front)

Ponto de atenção:
- Este app expõe rotas de AUTH com namespace "boards".
"""

from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views  # mantém apenas o que realmente está em boards/views/__init__.py (ex: first_login)

from .views import cards as cards_views
from .views import card_edit_collab as card_edit_collab_views
from .views import checklists as checklist_views
from .views import calendar as calendar_views
from .views.mentions import board_mentions
from .views.polling import board_poll

from boards.views.modal_card_term import set_card_term_due, set_board_term_colors
from boards.views import camim_auth


from .views.activity import (
    activity_panel,
    add_activity,
    cards_unread_activity,
    quill_upload,
    set_activity_filter,
)

from .views.secrets import (
    add_secret,
    reveal_secret,
    delete_secret,
    edit_secret_viewers,
)

from boards.views.account import (
public_profile,
)

from boards.views.whats_new import whats_new_panel, whats_new_mark_seen

# Módulo "boards" (boards/views/boards.py)
from boards.views.boards import (
    # core
    index,
    board_detail,
    add_board,
    rename_board,
    delete_board,
    board_leave,
    board_share,
    board_share_remove,
    board_share_role_update,
    toggle_aggregator_column,
    # access request
    request_board_access,
    approve_board_access,
    deny_board_access,
    # transfer ownership
    transfer_owner_start,
    transfer_owner_confirm,
    # wallpaper / image
    update_board_wallpaper,
    remove_board_wallpaper,
    board_wallpaper_css,
    update_board_image,
    remove_board_image,
    # home wallpaper
    update_home_wallpaper,
    remove_home_wallpaper,
    home_wallpaper_css,
    # home groups / favorites
    home_group_create,
    home_group_rename,
    home_group_delete,
    home_group_move,
    home_group_item_add,
    home_group_item_remove,
    home_favorite_toggle,
    # onboarding da home
    boards_onboarding_dismiss,
)

from boards.views.boards_state import (
    boards_trash,
    boards_archived,
    archive_board,
    unarchive_board,
    trash_board,
    restore_board,
)


# Outros módulos (pelo seu urls atual)

from .views.search import board_search, home_search

# Colunas (assumindo boards/views/columns.py)
from .views import columns as columns_views
from .views.email_ingest import email_ingest_config, email_ingest_sync_now, email_ingest_test
from .views.column_automation import column_automation_modal, column_automation_delete
from .views.column_autosort import column_autosort_config, column_autosort_now

# Attachments / Quill (assumindo boards/views/attachments.py e boards/views/activity.py ou afins)
from .views import attachments as attachments_views

from .views import cards_state as cards_state_views

from boards.views.column_follow import toggle_column_follow

from boards.views.social import (
    social_page,
    social_set_unidade,
    social_dismiss_task,
    social_reply_seen,
    social_news_nudge,
    social_posts_panel,
    social_post_create,
    social_post_delete,
    social_post_edit,
    social_post_react,
    social_comment_react,
    social_comment_report,
    social_post_comment,
    social_post_reactors,
    social_post_viewers,
    social_post_feed_view,
    social_post_reach,
    social_post_detail,
    social_comments_mark_seen,
    mood_checkin,
    social_chatbot_message,
    social_ai_react,
    daily_checkin_save,
    social_cover_upload,
    social_avatar_upload,
    social_camila_chat,
    social_camila_history,
    social_unread_counts,
    social_pills_poll,
    social_user_network,
    social_friend_request,
    social_friend_accept,
    social_board_share,
    camila_admin,
    camila_knowledge_save,
    camila_knowledge_delete,
    camila_knowledge_toggle,
    camila_test_chat,
    camila_config_save,
    camila_import_json,
    camila_pop_list,
    camila_pop_upload,
    camila_pop_delete,
    camila_pop_toggle,
    camila_pop_resummarize,
    card_like_social,
    social_friends_feed,
    social_friend_reject,
    social_friend_remove,
    social_post_toggle_visibility,
    social_onboarding_done,
    chat_list,
    chat_messages,
    chat_send,
    chat_delete_message,
    chat_forward_message,
    chat_poll,
    chat_unread_total,
    chat_friends_list,
    chat_conversation_action,
    chat_sticker_create,
    chat_sticker_list,
    chat_sticker_delete,
    social_mention_search,
    social_user_search,
    social_posts_more,
    social_post_repost,
    social_post_page,
    social_post_full,
    social_health_analyze,
    social_health_chat,
    camila_news_list,
)

from boards.views.moderation_admin import (
    queue as moderation_queue,
    approve as moderation_approve,
    reject as moderation_reject,
)
from boards.views.moderation_user import my_under_review


app_name = "boards"

urlpatterns = [
    # ============================================================
    # HOME (lista de quadros)
    # ============================================================
    path("", index, name="boards_index"),

    # ============================================================
    # PERFIL PÚBLICO (rota curta por handle)
    # ============================================================
    path("u/<str:handle>/", public_profile, name="public_profile"),

    # ============================================================
    # SOCIAL (scrapbook / mood / chatbot)
    # ============================================================
    path("social/", social_page, name="social_page"),
    path("social/<int:user_id>/", social_page, name="social_page_user"),
    path("social/@<str:handle>/", social_page, name="social_page_handle"),
    path("users/<int:user_id>/social/", social_posts_panel, name="social_posts_panel"),
    path("social/post/create/", social_post_create, name="social_post_create"),
    path("social/post/<int:post_id>/delete/", social_post_delete, name="social_post_delete"),
    path("social/post/<int:post_id>/edit/", social_post_edit, name="social_post_edit"),
    path("social/post/<int:post_id>/toggle-visibility/", social_post_toggle_visibility, name="social_post_toggle_visibility"),
    path("social/post/<int:post_id>/react/", social_post_react, name="social_post_react"),
    path("social/comment/<int:comment_id>/react/", social_comment_react, name="social_comment_react"),
    path("social/comment/<int:comment_id>/report/", social_comment_report, name="social_comment_report"),
    path("social/post/<int:post_id>/comment/", social_post_comment, name="social_post_comment"),
    path("social/post/<int:post_id>/comments/seen/", social_comments_mark_seen, name="social_comments_mark_seen"),
    path("social/<int:user_id>/network/", social_user_network, name="social_user_network"),
    path("social/<int:user_id>/friend-request/", social_friend_request, name="social_friend_request"),
    path("social/<int:user_id>/friend-accept/", social_friend_accept, name="social_friend_accept"),
    path("social/<int:user_id>/friend-reject/", social_friend_reject, name="social_friend_reject"),
    path("social/<int:user_id>/friend-remove/", social_friend_remove, name="social_friend_remove"),
    path("social/board-share/", social_board_share, name="social_board_share"),
    path("social/set-unidade/", social_set_unidade, name="social_set_unidade"),
    path("social/task/<int:card_id>/dismiss/", social_dismiss_task, name="social_dismiss_task"),
    path("card/<int:card_id>/like-social/", card_like_social, name="card_like_social"),
    path("social/friends-feed/", social_friends_feed, name="social_friends_feed"),
    path("social/comment/<int:comment_id>/reply-seen/", social_reply_seen, name="social_reply_seen"),
    path("social/news-nudge/", social_news_nudge, name="social_news_nudge"),
    path("social/mood/", mood_checkin, name="mood_checkin"),
    path("social/chat/", social_chatbot_message, name="social_chatbot_message"),
    path("social/ai-react/", social_ai_react, name="social_ai_react"),
    path("social/checkin/", daily_checkin_save, name="daily_checkin_save"),
    path("social/cover/", social_cover_upload, name="social_cover_upload"),
    path("social/avatar/", social_avatar_upload, name="social_avatar_upload"),
    path("social/unread/", social_unread_counts, name="social_unread_counts"),
    path("social/pills/", social_pills_poll, name="social_pills_poll"),
    path("social/camila/", social_camila_chat, name="social_camila_chat"),
    path("social/camila/history/", social_camila_history, name="social_camila_history"),
    path("social/post/<int:post_id>/reactors/", social_post_reactors, name="social_post_reactors"),
    path("social/post/<int:post_id>/viewers/", social_post_viewers, name="social_post_viewers"),
    path("social/post/<int:post_id>/feed-view/", social_post_feed_view, name="social_post_feed_view"),
    path("social/post/<int:post_id>/reach/", social_post_reach, name="social_post_reach"),
    path("social/posts/<int:post_id>/", social_post_detail, name="social_post_detail"),
    path("social/onboarding-done/", social_onboarding_done, name="social_onboarding_done"),

    # Chat direto entre amigos
    path("chat/", chat_list, name="chat_list"),
    path("chat/<int:user_id>/messages/", chat_messages, name="chat_messages"),
    path("chat/<int:user_id>/send/", chat_send, name="chat_send"),
    path("chat/<int:user_id>/poll/", chat_poll, name="chat_poll"),
    path("chat/message/<int:message_id>/delete/", chat_delete_message, name="chat_delete_message"),
    path("chat/message/<int:message_id>/forward/", chat_forward_message, name="chat_forward_message"),
    path("chat/unread/", chat_unread_total, name="chat_unread_total"),
    path("chat/friends/", chat_friends_list, name="chat_friends_list"),
    path("chat/<int:conv_id>/action/", chat_conversation_action, name="chat_conversation_action"),
    path("chat/stickers/", chat_sticker_list, name="chat_sticker_list"),
    path("chat/stickers/create/", chat_sticker_create, name="chat_sticker_create"),
    path("chat/stickers/<int:sticker_id>/delete/", chat_sticker_delete, name="chat_sticker_delete"),
    path("social/mentions/", social_mention_search, name="social_mention_search"),
    path("social/users/search/", social_user_search, name="social_user_search"),
    path("social/<int:user_id>/posts/more/", social_posts_more, name="social_posts_more"),
    path("social/post/<int:post_id>/repost/", social_post_repost, name="social_post_repost"),
    path("social/post/<int:post_id>/view/", social_post_page, name="social_post_page"),
    path("social/post/<int:post_id>/full/", social_post_full, name="social_post_full"),

    # Saúde e Bem Estar
    path("social/health/analyze/", social_health_analyze, name="social_health_analyze"),
    path("social/health/chat/", social_health_chat, name="social_health_chat"),

    # Camila News
    path("social/camila/news/", camila_news_list, name="camila_news_list"),

    # Moderação — usuário vê suas próprias publicações em análise
    path("social/meus-em-analise/", my_under_review, name="social_my_under_review"),

    # Moderação — fila staff
    path("moderation/queue/", moderation_queue, name="moderation_queue"),
    path("moderation/<int:case_id>/approve/", moderation_approve, name="moderation_approve"),
    path("moderation/<int:case_id>/reject/", moderation_reject, name="moderation_reject"),

    # Camila.AI Admin (staff only)
    path("camila/", camila_admin, name="camila_admin"),
    path("camila/save/", camila_knowledge_save, name="camila_knowledge_save"),
    path("camila/<int:entry_id>/delete/", camila_knowledge_delete, name="camila_knowledge_delete"),
    path("camila/<int:entry_id>/toggle/", camila_knowledge_toggle, name="camila_knowledge_toggle"),
    path("camila/test/", camila_test_chat, name="camila_test_chat"),
    path("camila/config/", camila_config_save, name="camila_config_save"),
    path("camila/import-json/", camila_import_json, name="camila_import_json"),
    path("camila/pops/", camila_pop_list, name="camila_pop_list"),
    path("camila/pops/upload/", camila_pop_upload, name="camila_pop_upload"),
    path("camila/pops/<int:pop_id>/delete/", camila_pop_delete, name="camila_pop_delete"),
    path("camila/pops/<int:pop_id>/toggle/", camila_pop_toggle, name="camila_pop_toggle"),
    path("camila/pops/<int:pop_id>/resummarize/", camila_pop_resummarize, name="camila_pop_resummarize"),

    # ============================================================
    # IDCamim OAuth2
    # ============================================================
    path("auth/camim/login/",    camim_auth.camim_login,    name="camim_login"),
    path("auth/camim/callback/", camim_auth.camim_callback, name="camim_callback"),

    # ============================================================
    # AUTH / CONTAS (login/logout/primeiro login/recuperação senha)
    # ============================================================
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/first-login/", views.first_login, name="first_login"),
    path(
        "accounts/password_reset/",
        auth_views.PasswordResetView.as_view(
            template_name="registration/password_reset_form.html",
            email_template_name="registration/password_reset_email.txt",
            html_email_template_name="registration/password_reset_email.html",
            subject_template_name="registration/password_reset_subject.txt",
            success_url=reverse_lazy("boards:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "accounts/password_reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="registration/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path(
        "accounts/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="registration/password_reset_confirm.html",
            success_url=reverse_lazy("boards:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "accounts/reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="registration/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),

    # ============================================================
    # ADMIN / USUÁRIOS (opcional)
    # ============================================================
    path("users/create/", views.create_user, name="create_user"),

    # ============================================================
    # BOARDS — CRUD / VISUALIZAÇÃO / AÇÕES DE QUADRO
    # ============================================================
    path("board/add/", add_board, name="add_board"),
    path("board/<int:board_id>/", board_detail, name="board_detail"),
    path("board/<int:board_id>/search/", board_search, name="board_search"),
    path("board/<int:board_id>/rename/", rename_board, name="rename_board"),
    path("board/<int:board_id>/delete/", delete_board, name="delete_board"),
    path("board/<int:board_id>/leave/", board_leave, name="board_leave"),

    # Criar Card From Email (ingestão IMAP -> cards)
    path("board/<int:board_id>/email-ingest/", email_ingest_config, name="email_ingest_config"),
    path("board/<int:board_id>/email-ingest/sync/", email_ingest_sync_now, name="email_ingest_sync_now"),
    path("board/<int:board_id>/email-ingest/test/", email_ingest_test, name="email_ingest_test"),



    path("board/<int:board_id>/archive/", archive_board, name="archive_board"),
    path("board/<int:board_id>/unarchive/", unarchive_board, name="unarchive_board"),

    path("board/<int:board_id>/trash-board/", trash_board, name="trash_board"),
    path("board/<int:board_id>/restore/", restore_board, name="restore_board"),
    path("boards/trash/", boards_trash, name="boards_trash"),
    path("boards/archived/", boards_archived, name="boards_archived"),


    # ============================================================
    # CARDS — Arquivo / Lixeira (Cards)
    # ============================================================
    
    path("card/<int:card_id>/archive/", cards_state_views.archive_card, name="archive_card"),
    path("card/<int:card_id>/unarchive/", cards_state_views.unarchive_card, name="unarchive_card"),
    path("card/<int:card_id>/trash/", cards_state_views.trash_card, name="trash_card"),
    path("card/<int:card_id>/restore/", cards_state_views.restore_card, name="restore_card"),
    # CARDS — Arquivo / Lixeira (PÁGINAS)
    path("board/<int:board_id>/trash/", cards_state_views.trash, name="trash"),
    path("board/<int:board_id>/archived/", cards_state_views.archived, name="archived"),



    # ============================================================
    # BOARDS — COMPARTILHAMENTO (modal + remove membro)
    # ============================================================
    path("board/<int:board_id>/share/", board_share, name="board_share"),
    path("board/<int:board_id>/share/submit/", board_share, name="board_share_submit"),
    path(
        "board/<int:board_id>/share/remove/<int:user_id>/",
        board_share_remove,
        name="board_share_remove",
    ),
    path(
        "board/<int:board_id>/share/role/<int:user_id>/",
        board_share_role_update,
        name="board_share_role_update",
    ),

    # ============================================================
    # BOARDS — ACESSO SEM CONVITE (solicitar / aprovar / negar)
    # ============================================================
    path(
        "boards/<int:board_id>/request-access/",
        request_board_access,
        name="board_request_access",
    ),
    path(
        "boards/<int:board_id>/approve-access/<int:user_id>/",
        approve_board_access,
        name="board_approve_access",
    ),
    path(
        "boards/<int:board_id>/deny-access/<int:user_id>/",
        deny_board_access,
        name="board_deny_access",
    ),
    path("board/<int:board_id>/access-requests/poll/", views.board_access_requests_poll, name="board_access_requests_poll"),


    # ============================================================
    # BOARDS — COLUNAS (criar / reordenar / seguir)
    # ============================================================
    path("board/<int:board_id>/add_column/", columns_views.add_column, name="add_column"),
    path("board/<int:board_id>/columns/reorder/", columns_views.reorder_columns, name="reorder_columns"),
    path("column/<int:column_id>/follow/", toggle_column_follow, name="toggle_column_follow"),

    # ============================================================
    # BOARDS — WALLPAPER / CSS
    # ============================================================
    path("board/<int:board_id>/wallpaper/", update_board_wallpaper, name="update_board_wallpaper"),
    path("board/<int:board_id>/wallpaper/remove/", remove_board_wallpaper, name="remove_board_wallpaper"),
    path("board/<int:board_id>/wallpaper.css", board_wallpaper_css, name="board_wallpaper_css"),

    # ============================================================
    # BOARDS — IMAGEM (capa do quadro)
    # ============================================================
    path("board/<int:board_id>/image/", update_board_image, name="update_board_image"),
    path("board/<int:board_id>/image/remove/", remove_board_image, name="remove_board_image"),

    # ============================================================
    # BOARDS — POLLING (sincronização leve)
    # ============================================================
    path("board/<int:board_id>/poll/", board_poll, name="board_poll"),

    # ============================================================
    # BOARDS — PRAZOS (term due + cores do board)
    # ============================================================
    path("card/<int:card_id>/term-due/", set_card_term_due, name="set_card_term_due"),
    path("board/<int:board_id>/term-colors/", set_board_term_colors, name="set_board_term_colors"),

    # ============================================================
    # BOARDS — AGREGADOR DE COLUNAS
    # ============================================================
    path(
        "board/<int:board_id>/toggle-aggregator/",
        toggle_aggregator_column,
        name="toggle_aggregator_column",
    ),

    # ============================================================
    # BOARDS — PREFERÊNCIAS DE USUÁRIO (filtros, agrupamentos pessoais, favoritos)
    # ============================================================
    path(
        "activity/filter/set/",
        views.set_activity_filter,
        name="set_activity_filter",
    ),
    # ============================================================
    # BOARDS — TRANSFERÊNCIA DE TITULARIDADE (OWNER -> OWNER)
    # ============================================================
    path(
        "board/<int:board_id>/transfer_owner/start/",
        transfer_owner_start,
        name="transfer_owner_start",
    ),
    path(
        "board/<int:board_id>/transfer_owner/confirm/",
        transfer_owner_confirm,
        name="transfer_owner_confirm",
    ),

    # ============================================================
    # BOARDS — CALENDÁRIO
    # ============================================================
    path("calendar/cards/", calendar_views.calendar_cards, name="calendar_cards"),
    path(
        "card/<int:card_id>/calendar-date/",
        calendar_views.card_calendar_date_update,
        name="card_calendar_date_update",
    ),

    # ============================================================
    # HOME GROUPS / FAVORITOS (agrupamentos pessoais)
    # ============================================================
    path("home/groups/create/", home_group_create, name="home_group_create"),
    path("home/groups/<int:group_id>/rename/", home_group_rename, name="home_group_rename"),
    path("home/groups/<int:group_id>/delete/", home_group_delete, name="home_group_delete"),
    path("home/groups/<int:group_id>/move/", home_group_move, name="home_group_move"),
    path("home/groups/<int:group_id>/items/add/", home_group_item_add, name="home_group_item_add"),
    path(
        "home/groups/<int:group_id>/items/<int:board_id>/remove/",
        home_group_item_remove,
        name="home_group_item_remove",
    ),
    path("home/favorites/toggle/<int:board_id>/", home_favorite_toggle, name="home_favorite_toggle"),
    path("home/search/", home_search, name="home_search"),
    path("home/onboarding/done/", boards_onboarding_dismiss, name="boards_onboarding_dismiss"),

    # ============================================================
    # HOME WALLPAPER (papel de parede da home)
    # ============================================================
    path("home/wallpaper/", update_home_wallpaper, name="update_home_wallpaper"),
    path("home/wallpaper/remove/", remove_home_wallpaper, name="remove_home_wallpaper"),
    path("home/wallpaper.css", home_wallpaper_css, name="home_wallpaper_css"),

    # ============================================================
    # COLUMNS (ações por coluna)
    # ============================================================
    path("column/<int:column_id>/add_card/", cards_views.add_card, name="add_card"),
    path("column/<int:column_id>/delete/", columns_views.delete_column, name="delete_column"),
    path("column/<int:column_id>/rename/", columns_views.rename_column, name="rename_column"),
    path("column/<int:column_id>/theme/", columns_views.set_column_theme, name="set_column_theme"),
    path("column/<int:column_id>/reorder_cards/", cards_views.reorder_cards_in_column, name="reorder_cards_in_column"),

    # Automação da coluna (gatilho card entra/sai -> ação)
    path("column/<int:column_id>/automation/", column_automation_modal, name="column_automation_modal"),
    path("column-automation/<int:automation_id>/delete/", column_automation_delete, name="column_automation_delete"),

    # Auto-ordenação agendada da coluna
    path("column/<int:column_id>/autosort/", column_autosort_config, name="column_autosort_config"),
    path("column/<int:column_id>/autosort/now/", column_autosort_now, name="column_autosort_now"),
    path("column/<int:column_id>/export/", columns_views.export_column, name="export_column"),
    path("column-import/<int:board_id>/", columns_views.import_column_form, name="import_column_form"),
    path("column-import/<int:board_id>/execute/", columns_views.import_column_execute, name="import_column_execute"),
    path("import/trello/", columns_views.import_trello_form, name="import_trello_form"),
    path("import/trello/execute/", columns_views.import_trello_execute, name="import_trello_execute"),
    path("import/trello/from-url/", columns_views.import_trello_from_url, name="import_trello_from_url"),

    # ============================================================
    # CARDS (modal / CRUD / mover / anexos / atividade)
    # ============================================================
    path("card/<int:card_id>/modal/", cards_views.card_modal, name="card_modal"),
    path("card/<int:card_id>/snippet/", cards_views.card_snippet, name="card_snippet"),
    path("card/<int:card_id>/similar/", cards_views.card_similar, name="card_similar"),
    path("card/<int:card_id>/edit/", cards_views.edit_card, name="edit_card"),
    path("card/<int:card_id>/update/", cards_views.update_card, name="update_card"),
    path("card/<int:card_id>/delete/", cards_views.delete_card, name="delete_card"),

    # ============================================================
    # Edição colaborativa (soft lock + live preview via WS)
    # ============================================================
    path(
        "card/<int:card_id>/field/<str:field>/lock/",
        card_edit_collab_views.card_field_lock,
        name="card_field_lock",
    ),
    path(
        "card/<int:card_id>/field/<str:field>/typing/",
        card_edit_collab_views.card_field_typing,
        name="card_field_typing",
    ),
    path(
        "card/<int:card_id>/field/<str:field>/release/",
        card_edit_collab_views.card_field_release,
        name="card_field_release",
    ),

    # Tags
    path("cards/<int:card_id>/tag-color/", cards_views.set_tag_color, name="set_tag_color"),
    path("card/<int:card_id>/remove_tag/", cards_views.remove_tag, name="remove_tag"),
    # Tag Catalog (etiquetas fixas do usuário, por board)
    path("board/<int:board_id>/tag-catalog/", cards_views.tag_catalog_get, name="tag_catalog_get"),
    path("board/<int:board_id>/tag-catalog/set/", cards_views.tag_catalog_set, name="tag_catalog_set"),
    path("board/<int:board_id>/tag-catalog/delete/", cards_views.tag_catalog_delete, name="tag_catalog_delete"),


    # Capa do card
    path("card/<int:card_id>/cover/set/", cards_views.set_card_cover, name="set_card_cover"),
    path("card/<int:card_id>/cover/remove/", cards_views.remove_card_cover, name="remove_card_cover"),

    # Duplicar card
    path("card/<int:card_id>/duplicate/", cards_views.duplicate_card, name="duplicate_card"),

    # Mover card
    path("move-card/", cards_views.move_card, name="move_card"),
    path("card/<int:card_id>/move/options/", cards_views.card_move_options, name="card_move_options"),
    path("card/<int:card_id>/move/suggestions/", cards_views.card_move_suggestions, name="card_move_suggestions"),

    # Atividade (painel / add / quill upload) — ajuste conforme seu projeto real
    path("card/<int:card_id>/activity/panel/", activity_panel, name="activity_panel"),
    path("card/<int:card_id>/activity/add/", add_activity, name="add_activity"),

    # snippets/segredos de card (curl com chave etc.)
    path("card/<int:card_id>/secret/add/", add_secret, name="add_secret"),
    path("card/<int:card_id>/secret/<int:secret_id>/reveal/", reveal_secret, name="reveal_secret"),
    path("card/<int:card_id>/secret/<int:secret_id>/viewers/", edit_secret_viewers, name="edit_secret_viewers"),
    path("card/<int:card_id>/secret/<int:secret_id>/delete/", delete_secret, name="delete_secret"),
    path("activity/filter/set/", set_activity_filter, name="set_activity_filter"),
    path("quill/upload/", quill_upload, name="quill_upload"),

    path(
        "board/<int:board_id>/cards/unread-activity/",
        cards_unread_activity,
        name="cards_unread_activity",
    ),

    # Menções (board)
    path("board/<int:board_id>/mentions/", board_mentions, name="board_mentions"),

    # Anexos
    path("card/<int:card_id>/attachments/add/", attachments_views.add_attachment, name="add_attachment"),
    path(
        "card/<int:card_id>/attachments/<int:attachment_id>/delete/",
        attachments_views.delete_attachment,
        name="delete_attachment",
    ),

    path("card/<int:card_id>/follow/", cards_state_views.toggle_card_follow, name="toggle_card_follow"),


    # ============================================================
    # CHECKLISTS (modal do card)
    # ============================================================
    path("card/<int:card_id>/checklist/add/", checklist_views.checklist_add, name="checklist_add"),
    path("checklist/<int:checklist_id>/rename/", checklist_views.checklist_rename, name="checklist_rename"),
    path("checklist/<int:checklist_id>/delete/", checklist_views.checklist_delete, name="checklist_delete"),

    path("checklist/<int:checklist_id>/item/add/", checklist_views.checklist_add_item, name="checklist_add_item"),
    path("checklist/item/<int:item_id>/toggle/", checklist_views.checklist_toggle_item, name="checklist_toggle_item"),
    path("checklist/item/<int:item_id>/delete/", checklist_views.checklist_delete_item, name="checklist_delete_item"),
    path("checklist/item/<int:item_id>/update/", checklist_views.checklist_update_item, name="checklist_update_item"),

    path("card/<int:card_id>/checklists/reorder/", checklist_views.checklists_reorder, name="checklists_reorder"),
    path("card/<int:card_id>/checklist-items/reorder/", checklist_views.checklist_items_reorder, name="checklist_items_reorder"),

    # Legado (se ainda existir)
    path("checklist/<int:checklist_id>/move/", checklist_views.checklist_move, name="checklist_move"),
    path("checklist/item/<int:item_id>/move-up/", checklist_views.checklist_move_up, name="checklist_move_up"),
    path("checklist/item/<int:item_id>/move-down/", checklist_views.checklist_move_down, name="checklist_move_down"),

    # ============================================================
    # CONTA / PERFIL (modal do usuário)
    # (mantendo via views/__init__.py porque você reexporta account/profiles)
    # ============================================================
    path("account/modal/", views.account_modal, name="account_modal"),
    path("account/profile/update/", views.account_profile_update, name="account_profile_update"),
    path("account/password/change/", views.account_password_change, name="account_password_change"),
    path("account/avatar/update/", views.account_avatar_update, name="account_avatar_update"),
    path("account/avatar/choose/", views.account_avatar_choice_update, name="account_avatar_choice_update"),
    path("account/identity-label/update/", views.account_identity_label_update, name="account_identity_label_update"),

    # ============================================================
    # PERFIL READ-ONLY (modal ao clicar em avatar de outra pessoa)
    # ============================================================
    path(
        "users/<int:user_id>/profile/readonly/",
        views.user_profile_readonly_modal,
        name="user_profile_readonly_modal",
    ),

    # ============================================================
    # HISTÓRICO / NÃO LIDOS
    # ============================================================
    path("board/<int:board_id>/history/", views.board_history_modal, name="board_history_modal"),
    path("board/<int:board_id>/history/unread-count/", views.board_history_unread_count, name="board_history_unread_count"),

    # ============================================================
    # WHATS NEW — novidades do sistema
    # ============================================================
    path("whats-new/", whats_new_panel, name="whats_new_panel"),
    path("whats-new/seen/", whats_new_mark_seen, name="whats_new_mark_seen"),
]
# END file boards/urls.py
