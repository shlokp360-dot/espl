"""
The addresses task management lives at.

⚠ THE PROJECT IS A QUERY STRING, NOT PART OF THE PATH — /tasks/?project=3
    rather than /projects/3/tasks/. The BOQ and the BOM belong to one project
    and are reached through it; the board is reached from the LAUNCHPAD, by
    somebody who has not chosen a project yet and needs the picker to choose
    with. A project in the path would mean no address to send them to.

⚠ THE THREE ADDS ARE POST-ONLY. Same rule as everywhere else here: a browser,
    a link preview or a back button re-fetches a GET freely, and "add" that
    works by being visited will eventually be visited by accident.
"""
from django.urls import path

from tasks import views

urlpatterns = [
    path("tasks/", views.board, name="task_board"),
    path("tasks/header/new/", views.header_new, name="task_header_new"),
    path("tasks/subtask/new/", views.subtask_new, name="task_subtask_new"),

    # Changing the plan. GET draws the form, POST saves it — the only two
    # addresses here that are not POST-only, because a form has to be shown.
    path("tasks/header/<int:header_id>/", views.header_edit, name="task_header_edit"),
    path("tasks/subtask/<int:subtask_id>/edit/", views.subtask_edit, name="task_subtask_edit"),
    # ⚠ The agreed substitute for dependencies: tick rows, move them together.
    path("tasks/subtasks/bulk/", views.subtasks_bulk, name="task_subtasks_bulk"),

    # ⚠ NO PROJECT HERE, AND THAT IS THE POINT. My work is everything waiting on
    #   one person wherever it is; the board is one site's whole plan.
    path("tasks/mine/", views.my_work, name="task_mine"),
    path("tasks/subtask/<int:subtask_id>/done/", views.subtask_done, name="task_subtask_done"),
    path("tasks/subtask/<int:subtask_id>/blocked/", views.subtask_blocked,
         name="task_subtask_blocked"),
    path("tasks/subtask/<int:subtask_id>/unblock/", views.subtask_unblock,
         name="task_subtask_unblock"),
    # A manager undoing a tick. The engineer cannot.
    path("tasks/subtask/<int:subtask_id>/reopen/", views.subtask_reopen,
         name="task_subtask_reopen"),

    # ⚠ ANCHOR: TASK-DELETE — the only two addresses here that destroy a record.
    #   POST-only like the rest, and for a stronger reason: a delete that works
    #   by being visited will eventually be visited by a link preview.
    path("tasks/subtask/<int:subtask_id>/delete/", views.subtask_delete,
         name="task_subtask_delete"),
    path("tasks/header/<int:header_id>/delete/", views.header_delete,
         name="task_header_delete"),

    path("tasks/schedule/", views.schedule, name="task_schedule"),
    path("tasks/people/", views.people, name="task_people"),
    path("tasks/delays/", views.delay_log, name="task_delay_log"),
]
