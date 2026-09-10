"""
The work board: one project's header tasks, the subtasks under them, and the
milestones drawn across them.

>>> ANCHOR: TASK-BOARD <<<

⚠ ONE PROJECT AT A TIME, AND THE PICKER IS THE FIRST THING ON THE SCREEN.
    Saahil, after finding the fault in the prototype: "I hope all new header task
    created are specific to a project, they should not be visible in other
    projects as all tasks are unique." Every query below is filtered by the
    chosen project, and the New-subtask box is filled from THAT project's
    headers — the prototype's version listed every header in the system, which
    is precisely how somebody would file Earthing under the wrong site.

⚠ WON PROJECTS ONLY — "have a project input option filtered from won projects".
    A quoted job has no site to work on. The filter is here on the screen, not a
    constraint in the database: a project can be Won today and Completed next
    year, and the tasks it collected must not become unreadable when it is.
    See `open_projects()` for what happens to a Completed one.

⚠ EVERY ADD BUTTON IS AT THE TOP OF THE SCREEN. His instruction, and it is about
    the site rather than the design: "bring all the add options on the top, if
    the list is long, how much will the user scroll". A project with forty header
    tasks would otherwise hide its own Add button a screen and a half down.

⚠ READING IS ONE PERMISSION AND CHANGING IS ANOTHER.
    `tasks.view` opens this screen and everybody has it. `tasks.manage` is what
    the three POST addresses below require, and what hides the buttons in the
    template. A site engineer sees the plan and cannot rewrite it.
"""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from accounts.perms import requires
from masters.models import Activity
from projects.models import Project
from tasks import schedule as schedule_geometry
from tasks.models import (
    DelayReason, Subtask, TaskHeader, capture_promise, finish,
)

User = get_user_model()

#: How many days a header task runs if nobody says otherwise.
DEFAULT_HEADER_DAYS = 7


def open_projects():
    """
    The projects a task may be attached to.

    ⚠ WON *AND* COMPLETED, not Won alone. Filtering to Won would be the literal
      reading of "filtered from won projects", and it would make every task on a
      finished building disappear from the picker on the day it was handed over —
      taking the record of who did what with it. Won is what makes a project
      eligible; Completed is what it becomes afterwards, and the history has to
      stay reachable.
    """
    return Project.objects.filter(
        status__in=[Project.Status.WON, Project.Status.COMPLETED]
    ).order_by("-status", "name")


def _chosen_project(request):
    """
    The project the screen is about, from `?project=`, falling back to the first.

    Returns None only when the company has no Won project at all, which is a
    real state on a fresh installation and not an error.
    """
    projects = list(open_projects())
    if not projects:
        return None, []

    wanted = request.GET.get("project") or request.POST.get("project")
    if wanted:
        for project in projects:
            if str(project.pk) == str(wanted):
                return project, projects
    return projects[0], projects


def _board_url(project):
    return f"{reverse('task_board')}?project={project.pk}" if project else reverse("task_board")


def _people():
    """Everybody who can sign in — the list an owner or an assignee comes from."""
    return User.objects.filter(is_active=True).order_by("first_name", "username")


def _typed_days(raw):
    """A duration in days, or None. Refuses zero and anything not a number."""
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return None
    return days if days >= 1 else None


# ------------------------------------------------------------------ the board
@requires("tasks.view")
def board(request):
    """One project's plan, headers with their subtasks underneath."""
    project, projects = _chosen_project(request)

    headers = []
    if project:
        # ⚠ prefetch_related, or this is one query per header on a screen that
        #   will hold thirty of them. The same mistake is written up three times
        #   in this project's own bug list.
        headers = list(
            TaskHeader.objects
            .filter(project=project)
            .select_related("activity", "owner")
            .prefetch_related("subtasks__assignee")
        )

    rows = []
    for header in headers:
        subtasks = list(header.subtasks.all())
        done, total = header.progress(subtasks)
        rows.append({
            "header": header,
            "subtasks": subtasks,
            "done": done,
            "total": total,
            # A bar with no subtasks reads 0%, not 100%. Nothing has been done.
            "percent": int(round(done * 100 / total)) if total else 0,
            "over": header.days_over_plan(subtasks),
        })

    return render(request, "tasks/board.html", {
        "project": project,
        "projects": projects,
        "rows": rows,
        "activities": Activity.objects.filter(is_active=True),
        "people": _people(),
        "priorities": Subtask.Priority.choices,
        # Read by the bulk bar at the top: moving dates outward needs a reason.
        "reasons": DelayReason.choices,
        "default_days": DEFAULT_HEADER_DAYS,
        # ⚠ The New-subtask box is filled from THIS project's headers and no
        #   others. See the note at the top of the file.
        "headers": headers,
    })


# ----------------------------------------------------------------- the adding
@require_POST
@requires("tasks.manage")
def header_new(request):
    """A package of work — "Earthing" — with an owner and a committed window."""
    project, _projects = _chosen_project(request)
    if project is None:
        messages.error(request, "There is no Won project to add work to.")
        return redirect("task_board")

    name = (request.POST.get("name") or "").strip()
    activity_id = request.POST.get("activity") or ""
    owner_id = request.POST.get("owner") or ""
    start = parse_date((request.POST.get("start") or "").strip())
    days = _typed_days(request.POST.get("days"))

    errors = []
    if not name:
        errors.append("A header task needs a name — "
                      "what the work is called on site, like Earthing.")
    elif TaskHeader.objects.filter(project=project, name__iexact=name).exists():
        # ⚠ CASE-INSENSITIVE, AND ONLY WITHIN THIS PROJECT. "Earthing" and
        #   "earthing" on one site are one job typed twice; on two sites they are
        #   two real jobs. The database constraint is the exact-case backstop.
        errors.append(f"{project.code} already has a header task called {name}.")

    activity = Activity.objects.filter(pk=activity_id).first() if activity_id else None
    if activity is None:
        errors.append("Choose the activity this work belongs to — "
                      "it is what ties the plan to the estimate.")
    if start is None:
        errors.append("A start date is needed. The finish is worked out from it.")
    if days is None:
        errors.append("Duration is a whole number of days, one or more.")

    if errors:
        for message in errors:
            messages.error(request, message)
        return redirect(_board_url(project))

    header = TaskHeader.objects.create(
        project=project, activity=activity, name=name,
        owner=User.objects.filter(pk=owner_id).first() if owner_id else None,
        start=start, days=days, created_by=request.user,
    )
    messages.success(
        request,
        f"{header.name} added — {header.start:%d/%m/%Y} to {header.planned_end:%d/%m/%Y}.")
    return redirect(_board_url(project))


def _warn_if_outside_the_window(request, subtask, header):
    """
    Say so when a task and its milestone do not overlap at all.

    ⚠ A PLAIN HELPER, AND IT MUST STAY ABOVE THE DECORATED VIEWS. Adding these
      two functions immediately before `subtask_new` put them BETWEEN its
      `@require_POST` / `@requires("tasks.manage")` and the view itself, so the
      decorators landed on this helper and `subtask_new` lost its permission
      entirely. A site engineer could post to it. Bug 20's shape — inserting
      text at a line number rather than at a structure — and the suite caught it
      in `test_matrix` and `tasks.tests`, which is exactly what those two are
      for. Nothing here is a view; nothing here takes a decorator.

    >>> ANCHOR: TASK-WINDOW-WARNING <<<
    ⚠⚠ IT WARNS, IT DOES NOT REFUSE, and that is the whole design. A milestone
       whose work runs past the window it was given is a REAL state — it is what
       the amber bar exists to show, and it arrives before anything is late. A
       hard block would outlaw it. What cannot be a plan is work that never
       touches its milestone's window at all: that is a typo, not a schedule.

    ⚠ NO OVERLAP AT ALL IS THE TEST, deliberately narrow. Anything that overlaps
      — starting early, finishing late, both — is already drawn on the chart as
      red or amber and does not need a second warning. A rule any broader would
      fire on the ordinary case, and a screen that warns about everything warns
      about nothing.

    WHY IT EXISTS. Saahil saved a milestone starting 14 August 2025 whose only
    task started 15 August 2026, and nothing said a word. The chart obediently
    drew a thirteen-month span to hold three weeks of work, and it looked broken.
    The system had in fact noticed — the row was amber — but amber says "the plan
    no longer fits", which is not the same sentence as "check the year".
    """
    if header is None:
        return
    if subtask.start <= header.planned_end and subtask.planned_end >= header.start:
        return

    if subtask.start > header.planned_end:
        distance = (subtask.start - header.planned_end).days
        where = f"{distance} day{'' if distance == 1 else 's'} after it finishes"
    else:
        distance = (header.start - subtask.planned_end).days
        where = f"{distance} day{'' if distance == 1 else 's'} before it starts"

    messages.warning(
        request,
        f"{subtask.title} ({subtask.start:%d/%m/%Y} – {subtask.planned_end:%d/%m/%Y}) falls "
        f"entirely outside {header.name} ({header.start:%d/%m/%Y} – "
        f"{header.planned_end:%d/%m/%Y}) — {where}. Saved anyway. Check the year if that "
        f"was not deliberate.")


def _warn_if_the_window_left_its_work(request, header):
    """
    The same warning from the other end: the milestone's dates moved away from
    every task under it.

    >>> ANCHOR: TASK-WINDOW-WARNING <<<
    ⚠⚠ THIS IS THE ONE THAT WOULD HAVE CAUGHT HIS. The mistyped year was on the
       MILESTONE — Site Work, 14 August 2025 — not on the task under it, so a
       check that only ran when a task was saved would have said nothing. A guard
       that catches the case you happened to think of is not a guard.

    ⚠ EVERY TASK, NOT ANY. One task outside the window is an ordinary overrun and
      the chart already colours it. All of them outside means the window itself
      is in the wrong place.
    """
    subtasks = list(header.subtasks.all())
    if not subtasks:
        return
    if any(row.start <= header.planned_end and row.planned_end >= header.start
           for row in subtasks):
        return

    count = len(subtasks)
    messages.warning(
        request,
        f"{header.name} ({header.start:%d/%m/%Y} – {header.planned_end:%d/%m/%Y}) no longer "
        f"covers {'its only task' if count == 1 else f'any of its {count} tasks'}. Saved anyway. "
        f"Check the year — a window nowhere near its own work stretches the whole chart.")


@require_POST
@requires("tasks.manage")
def subtask_new(request):
    """One person, one piece of work, one date."""
    project, _projects = _chosen_project(request)
    if project is None:
        messages.error(request, "There is no Won project to add work to.")
        return redirect("task_board")

    # ⚠ THE HEADER IS LOOKED UP *WITHIN THE PROJECT*, AND THAT IS THE WHOLE BUG.
    #   `get_object_or_404(TaskHeader, pk=…)` would accept a header id belonging
    #   to another site — which is exactly what the prototype did, and what
    #   Saahil caught by reading the dropdown. Filing a subtask against the wrong
    #   building is not something the person doing it would ever notice.
    header = TaskHeader.objects.filter(pk=request.POST.get("header") or 0,
                                       project=project).first()

    title = (request.POST.get("title") or "").strip()
    assignee_id = request.POST.get("assignee") or ""
    start = parse_date((request.POST.get("start") or "").strip())
    days = _typed_days(request.POST.get("days"))
    priority = (request.POST.get("priority") or Subtask.Priority.NORMAL).strip()

    errors = []
    if header is None:
        errors.append("Choose which header task this sits under, "
                      "on this project.")
    if not title:
        errors.append("Say what needs doing, in the words they would use on site.")
    if start is None:
        errors.append("A start date is needed.")
    if days is None:
        errors.append("Duration is a whole number of days, one or more.")
    if priority not in dict(Subtask.Priority.choices):
        priority = Subtask.Priority.NORMAL

    if errors:
        for message in errors:
            messages.error(request, message)
        return redirect(_board_url(project))

    subtask = Subtask.objects.create(
        header=header, title=title,
        assignee=User.objects.filter(pk=assignee_id).first() if assignee_id else None,
        start=start, days=days, priority=priority, created_by=request.user,
    )
    # ⚠ THE NOTIFICATION GOES HERE, and it is deliberately not written yet —
    #   "the user gets notified when there are new tasks assigned". It is one
    #   call to a `notify(person, event)` seam, in-app first and WhatsApp behind
    #   the same seam once the Meta business account exists. Putting the call in
    #   before there is anything to send would mean guessing the shape of it.
    who = subtask.assignee.get_full_name() if subtask.assignee else "nobody yet"
    messages.success(request, f"{subtask.title} added under {header.name} — {who}.")
    _warn_if_outside_the_window(request, subtask, header)
    return redirect(_board_url(project))


# ⚠⚠ `milestone_new` WAS DELETED HERE. A milestone is no longer a thing anybody
#    creates: it IS a header task, so the button that made one is the button
#    that makes a package. See the note where the model used to be in
#    tasks/models.py, and ANCHOR: MILESTONE-LINE for how it is drawn.
#
#    ⚠ THE URL NAME `task_milestone_new` GOES WITH IT. Nothing links to it, and
#      a POST address nobody can reach is exactly the orphaned flow the sweep
#      after slice 5 was written to find.
# ----------------------------------------------------------------- editing
#
# >>> ANCHOR: TASK-RESCHEDULE <<<
#
# ⚠ MOVING A DATE IS A DIFFERENT ACT FROM MISSING ONE, AND BOTH ARE RECORDED.
#     Saahil's decision: "keep the first promise". The team works to the new
#     date; the original stays on the row so lateness can still be read against
#     what was first committed to. Rescheduling therefore CANNOT make a late job
#     look like an on-time one, which is the only way an editable plan stays
#     honest.
#
# ⚠ AND THE MANAGER GIVES THE REASON, NOT THE ENGINEER. The person who moved the
#     plan is the one who knows why it moved. Without this the delay log would
#     quietly lose every day that was replanned rather than missed — which, on a
#     site, is most of them.
#
# ⚠ PULLING WORK FORWARD IS NEVER A DELAY. `capture_promise` returns zero when
#     the finish does not move outward, and no reason is asked for.

@requires("tasks.manage")
def header_edit(request, header_id):
    """Rename it, hand it to somebody else, or move the window."""
    header = get_object_or_404(
        TaskHeader.objects.select_related("project", "activity"), pk=header_id)
    errors = []

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        activity_id = request.POST.get("activity") or ""
        owner_id = request.POST.get("owner") or ""
        start = parse_date((request.POST.get("start") or "").strip())
        days = _typed_days(request.POST.get("days"))
        reason = (request.POST.get("shift_reason") or "").strip()
        note = (request.POST.get("shift_note") or "").strip()

        activity = Activity.objects.filter(pk=activity_id).first() if activity_id else None

        if not name:
            errors.append("A header task needs a name.")
        elif TaskHeader.objects.filter(project=header.project, name__iexact=name) \
                               .exclude(pk=header.pk).exists():
            errors.append(f"{header.project.code} already has a header task called {name}.")
        if activity is None:
            errors.append("Choose the activity this work belongs to.")
        if start is None:
            errors.append("A start date is needed.")
        if days is None:
            errors.append("Duration is a whole number of days, one or more.")

        moved = 0
        if not errors and (start != header.start or days != header.days):
            # ⚠ Worked out on a COPY of the dates, so a refusal below leaves the
            #   row exactly as it was rather than half-moved.
            moved = (finish(start, days) -header.promised_end).days
            if moved > 0 and reason not in dict(DelayReason.choices):
                errors.append(
                    f"This pushes the finish {moved} day{'s' if moved != 1 else ''} past what was "
                    "first promised. Say why the plan moved.")

        if not errors:
            if start != header.start or days != header.days:
                shifted = capture_promise(header, start, days)
                if shifted:
                    header.shift_reason, header.shift_note = reason, note
            header.name, header.activity = name, activity
            header.owner = User.objects.filter(pk=owner_id).first() if owner_id else None
            header.save()
            messages.success(request, f"{header.name} saved.")
            _warn_if_the_window_left_its_work(request, header)
            return redirect(_board_url(header.project))

        for message in errors:
            messages.error(request, message)

    return render(request, "tasks/header_form.html", {
        "header": header,
        "project": header.project,
        "activities": Activity.objects.filter(is_active=True),
        "people": _people(),
        "reasons": DelayReason.choices,
    })


@requires("tasks.manage")
def subtask_edit(request, subtask_id):
    """Retitle it, hand it to somebody else, change its priority, move its dates."""
    subtask = get_object_or_404(
        Subtask.objects.select_related("header", "header__project", "assignee"), pk=subtask_id)
    errors = []

    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        assignee_id = request.POST.get("assignee") or ""
        start = parse_date((request.POST.get("start") or "").strip())
        days = _typed_days(request.POST.get("days"))
        priority = (request.POST.get("priority") or subtask.priority).strip()
        reason = (request.POST.get("shift_reason") or "").strip()
        note = (request.POST.get("shift_note") or "").strip()

        if not title:
            errors.append("Say what needs doing.")
        if start is None:
            errors.append("A start date is needed.")
        if days is None:
            errors.append("Duration is a whole number of days, one or more.")
        if priority not in dict(Subtask.Priority.choices):
            priority = Subtask.Priority.NORMAL

        moved = 0
        if not errors and (start != subtask.start or days != subtask.days):
            moved = (finish(start, days) -subtask.promised_end).days
            if moved > 0 and reason not in dict(DelayReason.choices):
                errors.append(
                    f"This pushes the finish {moved} day{'s' if moved != 1 else ''} past what was "
                    "first promised. Say why the plan moved.")

        if not errors:
            was = subtask.assignee
            if start != subtask.start or days != subtask.days:
                shifted = capture_promise(subtask, start, days)
                if shifted:
                    subtask.shift_reason, subtask.shift_note = reason, note
            subtask.title, subtask.priority = title, priority
            subtask.assignee = User.objects.filter(pk=assignee_id).first() if assignee_id else None
            subtask.save()
            # ⚠ THE NOTIFICATION SEAM AGAIN — handing somebody else's work to a
            #   new person is exactly the event worth sending. Empty until the
            #   channel is decided; see subtask_new.
            if subtask.assignee != was:
                messages.success(
                    request,
                    f"{subtask.title} saved and moved to "
                    f"{subtask.assignee.get_full_name() if subtask.assignee else 'nobody'}.")
            else:
                messages.success(request, f"{subtask.title} saved.")
            # ⚠ ON EDIT TOO, NOT ONLY ON ADD. Rescheduling is where a year gets
            #   mistyped just as easily, and this is the screen that moves dates.
            _warn_if_outside_the_window(request, subtask, subtask.header)
            return redirect(_board_url(subtask.header.project))

        for message in errors:
            messages.error(request, message)

    return render(request, "tasks/subtask_form.html", {
        "subtask": subtask,
        "project": subtask.header.project,
        "people": _people(),
        "priorities": Subtask.Priority.choices,
        "reasons": DelayReason.choices,
    })


# ------------------------------------------------------------ in bulk
#
# ⚠ THIS IS THE SUBSTITUTE FOR DEPENDENCIES, AND IT WAS CHOSEN OVER THEM.
#     A dependency graph is the feature everybody asks for and nobody maintains:
#     one wrong link and the whole plan moves on its own. Saahil's agreed answer
#     was the blunt instrument — tick the rows that have to move, shift them all
#     by the same number of days, say why once. A person decides; the system
#     does the typing.

@require_POST
@requires("tasks.manage")
def subtasks_bulk(request):
    """Shift the ticked rows by N days, or hand them all to somebody else."""
    project, _projects = _chosen_project(request)
    if project is None:
        return redirect("task_board")

    # ⚠ FILTERED BY THE PROJECT, like everything else here. A posted id from
    #   another site is simply not found.
    chosen = list(Subtask.objects.filter(pk__in=request.POST.getlist("subtask"),
                                         header__project=project)
                  .select_related("header"))
    if not chosen:
        messages.error(request, "Tick the subtasks you want to change first.")
        return redirect(_board_url(project))

    action = request.POST.get("action")

    if action == "reassign":
        person = User.objects.filter(pk=request.POST.get("assignee") or 0).first()
        for subtask in chosen:
            subtask.assignee = person
            subtask.save(update_fields=["assignee"])
        messages.success(
            request,
            f"{len(chosen)} subtask{'s' if len(chosen) != 1 else ''} moved to "
            f"{person.get_full_name() if person else 'nobody'}.")
        return redirect(_board_url(project))

    if action == "shift":
        try:
            by = int(request.POST.get("days") or 0)
        except ValueError:
            by = 0
        if by == 0:
            messages.error(request, "Say how many days to move them by.")
            return redirect(_board_url(project))

        reason = (request.POST.get("shift_reason") or "").strip()
        # ⚠ Only a shift OUTWARD needs a reason. Pulling work forward is not a
        #   delay and must not be made to look like one.
        if by > 0 and reason not in dict(DelayReason.choices):
            messages.error(request, "Say why the plan is moving before shifting dates.")
            return redirect(_board_url(project))

        for subtask in chosen:
            shifted = capture_promise(subtask, subtask.start + timedelta(days=by), subtask.days)
            if shifted:
                subtask.shift_reason, subtask.shift_note = reason, (
                    request.POST.get("shift_note") or "").strip()
            subtask.save()

        messages.success(
            request,
            f"{len(chosen)} subtask{'s' if len(chosen) != 1 else ''} moved "
            f"{abs(by)} day{'s' if abs(by) != 1 else ''} {'later' if by > 0 else 'earlier'}.")
        return redirect(_board_url(project))

    messages.error(request, "Choose what to do with the ticked subtasks.")
    return redirect(_board_url(project))


# ---------------------------------------------------------------- my work
#
# >>> ANCHOR: TASK-MINE <<<
#
# ⚠ THE TICK BELONGS TO THE PERSON THE WORK IS ASSIGNED TO, AND TO NOBODY ELSE.
#     Saahil, on whether a manager confirms it afterwards: "the engineers tick is
#     final". A manager who could tick on somebody's behalf is a manager who will
#     eventually tick on somebody's behalf, and the one fact this screen exists to
#     collect — did the person who did the work say it was finished — would be
#     gone. `tasks.manage` does NOT open this door; see `_theirs()`.
#
#     The repair route for a mistaken tick is Reopen, which IS `tasks.manage`.
#     Correcting a record is a different act from making one.
#
# ⚠ THE FINISH DATE IS TODAY, CAPTURED, NEVER TYPED. His words: "the engineer
#     doesn't set the new date" — "recorded meaning, automatically captured, but
#     the reason should be entered by the user". Letting somebody type when they
#     finished is letting them decide whether they were late.
#
# ⚠ A LATE TICK CANNOT BE SAVED WITHOUT A REASON, AND AN ON-TIME ONE NEVER ASKS
#     FOR ONE. Nobody justifies being early, and a form that asks anyway teaches
#     people to pick the first option in the list.

def _theirs(request, subtask):
    """
    Whether this person may act on this row. Returns a refusal, or None.

    ⚠ NOT A PERMISSION QUESTION, AND THAT IS WHY IT IS NOT IN THE MATRIX. The
      matrix answers "may this role tick at all"; it has no way to express "may
      this person tick THAT line". Both checks are real and both are needed.
    """
    if subtask.assignee_id == request.user.pk:
        return None
    return HttpResponseForbidden(
        "This is somebody else's work to mark. A Project manager can reopen or "
        "reassign it, but the person doing a job is the one who says it is done.")


@requires("tasks.mine")
def my_work(request):
    """
    One person's rows, across every project.

    ⚠ ACROSS EVERY PROJECT, DELIBERATELY. The board is organised the way a
      manager thinks — one site, all its work. This is organised the way the
      person with the drill thinks: everything waiting on me, wherever it is.
      Same rows, and the whole reason for two screens.
    """
    today = timezone.localdate()

    mine = (Subtask.objects
            .filter(assignee=request.user)
            .select_related("header", "header__project", "header__activity")
            .order_by("start", "id"))

    live, finished = [], []
    for subtask in mine:
        overdue = subtask.days_overdue(today)
        row = {
            "subtask": subtask,
            "overdue": overdue,
            # ⚠ Worked out HERE and carried to the template, so the dialog can
            #   ask for a reason on exactly the rows that will need one. The view
            #   that saves works it out again — a hidden field the browser sends
            #   is a hidden field somebody can change.
            "will_be_late": subtask.planned_end < today,
        }
        (finished if subtask.status == Subtask.Status.DONE else live).append(row)

    # Blocked first, then the most overdue. Somebody opening this on a phone at
    # seven in the morning should not have to scroll to find what is stuck.
    live.sort(key=lambda row: (row["subtask"].status != Subtask.Status.BLOCKED,
                               -row["overdue"], row["subtask"].start))

    return render(request, "tasks/my_work.html", {
        "live": live,
        # The last twenty finished, newest first — enough to notice a wrong tick,
        # not so many that the screen becomes a history page.
        "finished": sorted(finished, key=lambda row: row["subtask"].finished_on or today,
                           reverse=True)[:20],
        "today": today,
        "overdue_count": sum(1 for row in live if row["overdue"]),
        "blocked_count": sum(1 for row in live
                             if row["subtask"].status == Subtask.Status.BLOCKED),
        "reasons": DelayReason.choices,
    })


def _mine_or_board(request, subtask):
    """Back where they came from — My work, or the board if they came from it."""
    if request.POST.get("from") == "board":
        return redirect(_board_url(subtask.header.project))
    return redirect("task_mine")


@require_POST
@requires("tasks.mine")
def subtask_done(request, subtask_id):
    """Finished. Today's date is recorded, and a late finish needs its reason."""
    subtask = get_object_or_404(
        Subtask.objects.select_related("header__project"), pk=subtask_id)
    denied = _theirs(request, subtask)
    if denied:
        return denied

    today = timezone.localdate()
    late_by = max(0, (today - subtask.planned_end).days)
    reason = (request.POST.get("delay_reason") or "").strip()
    note = (request.POST.get("delay_note") or "").strip()

    if late_by and reason not in dict(DelayReason.choices):
        # ⚠ REFUSED, NOT SAVED-WITH-A-BLANK. A delay log full of "no reason
        #   given" answers nothing, and the question it exists to answer —
        #   "which of these actually holds our sites up" — is the whole point.
        messages.error(
            request,
            f"{subtask.title} is {late_by} day{'s' if late_by != 1 else ''} past its date. "
            "Choose what held it up before marking it done.")
        return _mine_or_board(request, subtask)

    subtask.status = Subtask.Status.DONE
    subtask.finished_on = today
    subtask.delay_reason = reason if late_by else ""
    subtask.delay_note = note if late_by else ""
    # Finishing something clears the flag that said it was stuck.
    subtask.blocked_reason = ""
    subtask.blocked_note = ""
    subtask.save(update_fields=["status", "finished_on", "delay_reason", "delay_note",
                                "blocked_reason", "blocked_note"])

    if late_by:
        messages.success(
            request,
            f"{subtask.title} marked done — {late_by} day{'s' if late_by != 1 else ''} "
            f"past the plan, recorded as {dict(DelayReason.choices)[reason]}.")
    else:
        messages.success(request, f"{subtask.title} marked done.")
    return _mine_or_board(request, subtask)


@require_POST
@requires("tasks.mine")
def subtask_blocked(request, subtask_id):
    """
    Stuck, and why.

    ⚠ THE REASON IS AN INPUT, NOT AN AFTERTHOUGHT — Saahil: "reason is an input
      when you block". A row that says only "blocked" tells the manager to go and
      ask, which is the phone call this screen exists to save.

    ⚠ BLOCKING DOES NOT MOVE THE DATE. It stays where it was and the row keeps
      counting overdue, because that is the truth: the work has not happened.
    """
    subtask = get_object_or_404(
        Subtask.objects.select_related("header__project"), pk=subtask_id)
    denied = _theirs(request, subtask)
    if denied:
        return denied

    reason = (request.POST.get("blocked_reason") or "").strip()
    if reason not in dict(DelayReason.choices):
        messages.error(request, "Say what is holding it up — that is the point of flagging it.")
        return _mine_or_board(request, subtask)

    subtask.status = Subtask.Status.BLOCKED
    subtask.blocked_reason = reason
    subtask.blocked_note = (request.POST.get("blocked_note") or "").strip()
    subtask.save(update_fields=["status", "blocked_reason", "blocked_note"])
    messages.success(
        request,
        f"{subtask.title} flagged as blocked — {dict(DelayReason.choices)[reason]}.")
    return _mine_or_board(request, subtask)


@require_POST
@requires("tasks.mine")
def subtask_unblock(request, subtask_id):
    """Moving again. The reason it was stuck is cleared; the delay log keeps it."""
    subtask = get_object_or_404(
        Subtask.objects.select_related("header__project"), pk=subtask_id)
    denied = _theirs(request, subtask)
    if denied:
        return denied

    subtask.status = Subtask.Status.OPEN
    subtask.blocked_reason = ""
    subtask.blocked_note = ""
    subtask.save(update_fields=["status", "blocked_reason", "blocked_note"])
    messages.success(request, f"{subtask.title} is unblocked and back on your list.")
    return _mine_or_board(request, subtask)


@require_POST
@requires("tasks.manage")
def subtask_reopen(request, subtask_id):
    """
    A manager undoing a tick.

    ⚠ THIS IS THE ONLY WAY A DONE ROW GOES BACK, AND AN ENGINEER CANNOT DO IT.
      "The engineer's tick is final" cuts both ways: nobody overrules it, and
      nobody quietly takes it back either. Correcting the record is a manager's
      act and it is visible as one.
    """
    subtask = get_object_or_404(
        Subtask.objects.select_related("header__project"), pk=subtask_id)

    subtask.status = Subtask.Status.OPEN
    subtask.finished_on = None
    subtask.delay_reason = ""
    subtask.delay_note = ""
    subtask.save(update_fields=["status", "finished_on", "delay_reason", "delay_note"])
    whose = subtask.assignee.get_full_name() if subtask.assignee else "nobody"
    messages.success(request, f"{subtask.title} reopened — it is back on {whose}'s list.")
    return redirect(_board_url(subtask.header.project))


# --------------------------------------------------------- deleting the work
#
# >>> ANCHOR: TASK-DELETE <<<
# ⚠⚠ THE ONLY THING IN THIS MODULE THAT DESTROYS A RECORD. Everything else here
#    keeps what happened beside what was planned — a tick is captured, a reopen
#    is visible, a moved date keeps its first promise. Deletion keeps nothing,
#    and Saahil chose that knowingly when the two options were put to him:
#    option B, "Admin and project manager may delete ANY task, history included;
#    it is their judgement."
#
# ⚠ WHY NOT DEACTIVATE, WHICH IS THE RULE EVERYWHERE ELSE IN THIS APP. A vendor
#   or a material is referenced by documents that must stay readable years later
#   — deactivating is the only honest answer there. A task references nothing: no
#   money, no document, no material. A typo'd row is noise on a board somebody
#   reads every morning, and noise nobody can remove is how a board stops being
#   read. The rule is the same rule, applied to a different situation.


@require_POST
@requires("tasks.manage")
def subtask_delete(request, subtask_id):
    """
    Remove one task. Admin and project manager only.

    >>> ANCHOR: TASK-DELETE <<<
    ⚠ NOT THE ASSIGNEE, EVEN THOUGH THE TICK IS THEIRS. `tasks.mine` answers
      "may this person mark their own work done"; it cannot answer "may this
      person make the work disappear". Those are opposite acts — one records
      what happened, the other says it never did. The site engineer holds
      `tasks.mine` and not `tasks.manage`, so this door is closed to them.

    ⚠ ANY TASK, NOT ONLY AN OPEN ONE. He was asked and said any: a finished row
      filed against the wrong milestone is exactly the one somebody needs to
      remove, and refusing would leave it there forever.

    ⚠ THE DELAY LOG LOSES ITS ROW WITH IT, and that is the consequence worth
      naming rather than hiding. Days lost per reason is counted from the
      subtasks themselves — there is no separate log table — so deleting a late
      task removes its days from the count. That is why this is a manager's act
      and why the confirmation says what is being destroyed.
    """
    subtask = get_object_or_404(
        Subtask.objects.select_related("header__project"), pk=subtask_id)
    project = subtask.header.project
    title = subtask.title
    was_late = bool(subtask.days_late)

    subtask.delete()

    messages.success(
        request,
        f"{title} deleted." + (" Its delay is no longer counted in the log." if was_late else ""))
    return redirect(_board_url(project))


@require_POST
@requires("tasks.manage")
def header_delete(request, header_id):
    """
    Remove a milestone.

    ⚠⚠ REFUSED WHILE IT STILL HOLDS TASKS, and the message says how many. A
      cascade here would delete a fortnight of somebody's work from a button
      labelled with a phase name. Empty it first, deliberately, one row at a
      time — that is not friction, it is the decision being made where it can be
      seen.
    """
    header = get_object_or_404(
        TaskHeader.objects.select_related("project"), pk=header_id)
    project = header.project
    held = header.subtasks.count()

    if held:
        messages.error(
            request,
            f"{header.name} still holds {held} task{'' if held == 1 else 's'}. Delete or move "
            f"them first — a milestone will not take its tasks with it.")
        return redirect(_board_url(project))

    name = header.name
    header.delete()
    messages.success(request, f"{name} deleted.")
    return redirect(_board_url(project))


# ------------------------------------------------------------- the delay log
#
# >>> ANCHOR: TASK-DELAYS <<<
#
# ⚠ A REPOSITORY OF ITS OWN, NOT MARKS ON THE CHART. Saahil overruled the first
#     design in one sentence: "the delay messages should not be visible on the
#     chart, it should have a different log repository". A Gantt bar carries the
#     DIFFERENCE — the words live here.
#
# ⚠ IT IS A COUNTING SCREEN BEFORE IT IS A READING SCREEN. The reason is a fixed
#     list precisely so that "which of these actually holds our sites up" has an
#     answer, and that answer is the summary at the top, not the rows below it.
#
# ⚠ MANAGERS ONLY, AND THAT IS A DECISION THAT CAN BE WIDENED.
#     Whether an engineer sees everybody's delays was left open in the design
#     session. Manager-only is the reversible choice: their own late rows are
#     already on their own screen, so nobody is kept from their own record.

@requires("tasks.manage")
def delay_log(request):
    """What is stuck now, what finished late, and which reason keeps recurring."""
    project_id = (request.GET.get("project") or "").strip()
    person_id = (request.GET.get("person") or "").strip()
    reason = (request.GET.get("reason") or "").strip()

    rows = (Subtask.objects
            .select_related("assignee", "header", "header__project", "header__activity"))

    if project_id:
        rows = rows.filter(header__project_id=project_id)
    if person_id:
        rows = rows.filter(assignee_id=person_id)

    # ⚠ LATE IS "FINISHED AFTER ITS DATE", AND THE DATABASE CANNOT SAY THAT IN A
    #   FILTER — the planned end is start + days, computed in Python. So the
    #   candidates are narrowed in SQL (anything finished at all) and the
    #   arithmetic happens once per row, in one place, using the same property
    #   the screens use. One truth, not two.
    finished = rows.filter(status=Subtask.Status.DONE, finished_on__isnull=False)
    late = [row for row in finished if row.days_late > 0]
    if reason:
        late = [row for row in late if row.delay_reason == reason]
    late.sort(key=lambda row: row.finished_on, reverse=True)

    blocked = list(rows.filter(status=Subtask.Status.BLOCKED))
    if reason:
        blocked = [row for row in blocked if row.blocked_reason == reason]

    # ⚠ RESCHEDULED WORK IS THE THIRD KIND OF LOST DAY, AND THE EASIEST TO HIDE.
    #   A job replanned twice and then delivered on the new date is not late by
    #   any test — and it still arrived a fortnight after it was first promised.
    #   Counting only lateness would report that fortnight as zero.
    shifted = [row for row in rows.filter(original_start__isnull=False) if row.days_shifted > 0]
    if reason:
        shifted = [row for row in shifted if row.shift_reason == reason]
    shifted.sort(key=lambda row: row.days_shifted, reverse=True)

    # The summary: how often each reason appears, and how many days it has cost.
    labels = dict(DelayReason.choices)
    tally = {}

    def count(key, days):
        entry = tally.setdefault(key, {"count": 0, "days": 0})
        entry["count"] += 1
        entry["days"] += days

    for row in late:
        count(row.delay_reason, row.days_late)
    for row in shifted:
        count(row.shift_reason, row.days_shifted)

    # ⚠ "Not recorded" RATHER THAN A DASH. The screens refuse to save a late tick
    #   without a reason, so a blank here means a row written before that rule
    #   existed or straight through Admin — which is worth naming honestly
    #   instead of drawing as an empty box that looks like a fault.
    summary = sorted(
        ({"reason": key, "label": labels.get(key) or "Not recorded", **value}
         for key, value in tally.items()),
        key=lambda entry: (-entry["days"], -entry["count"]))

    return render(request, "tasks/delay_log.html", {
        "late": late,
        "blocked": blocked,
        "shifted": shifted,
        "summary": summary,
        "total_days": sum(row.days_late for row in late) + sum(row.days_shifted for row in shifted),
        "projects": open_projects(),
        "people": _people(),
        "reasons": DelayReason.choices,
        "project_id": project_id,
        "person_id": person_id,
        "reason": reason,
    })


# --------------------------------------------------------------- the schedule
@requires("tasks.view")
def schedule(request):
    """
    One project's plan as bars on a month scale.

    ⚠ EVERY NUMBER ON THIS SCREEN IS WORKED OUT IN `tasks/schedule.py`. This view
      chooses the project and hands over; the template draws what it is given.
      Geometry inside a template cannot be tested and gets copied.

    ⚠ *"A gantt chart is for the project manager, and the to-do is for the user"*
      — but it opens for everybody, because reading the plan is `tasks.view`. A
      person who cannot see what runs after their own row cannot see what they
      are holding up.
    """
    project, projects = _chosen_project(request)
    return render(request, "tasks/schedule.html", {
        "project": project,
        "projects": projects,
        "chart": schedule_geometry.build(project) if project else None,
    })


# ----------------------------------------------------------------- the people
@requires("tasks.manage")
def people(request):
    """
    Open work per person — who is carrying what, and who is stuck.

    ⚠ COUNTED IN PYTHON, NOT IN SQL, and for the same reason as the delay log:
      "overdue" and "late" are `start + days` against a real date, which is a
      property rather than a column. One row per subtask through the same
      arithmetic every other screen uses, instead of a second definition living
      in a database function.

    ⚠ IT IS NOT A LEAGUE TABLE AND MUST NOT BECOME ONE. The columns say what is
      on somebody's plate, not how good they are: a person with six overdue rows
      may be the only one on a site that is waiting for material. The delay log
      is where the reason lives, and it is one click away for exactly that.
    """
    today = timezone.localdate()
    project_id = (request.GET.get("project") or "").strip()

    rows = (Subtask.objects
            .select_related("assignee", "header", "header__project")
            .order_by("start", "id"))
    if project_id:
        rows = rows.filter(header__project_id=project_id)

    tally = {}
    for subtask in rows:
        key = subtask.assignee_id
        entry = tally.setdefault(key, {
            "person": subtask.assignee,     # None for unassigned, and shown as such
            "open": 0, "blocked": 0, "overdue": 0, "done": 0, "days_late": 0,
            "next": None,
        })
        if subtask.status == Subtask.Status.DONE:
            entry["done"] += 1
            entry["days_late"] += subtask.days_late
            continue
        if subtask.status == Subtask.Status.BLOCKED:
            entry["blocked"] += 1
        else:
            entry["open"] += 1
        if subtask.days_overdue(today):
            entry["overdue"] += 1
        # Rows arrive in date order, so the first one seen is the next one due.
        if entry["next"] is None:
            entry["next"] = subtask

    # ⚠ UNASSIGNED SITS AT THE TOP, NOT AT THE BOTTOM. Work nobody is holding is
    #   the one row on this screen that is somebody's job to fix today.
    people_rows = sorted(
        tally.values(),
        key=lambda entry: (entry["person"] is not None, -entry["overdue"], -entry["blocked"],
                           (entry["person"].get_full_name() if entry["person"] else "")))

    return render(request, "tasks/people.html", {
        "rows": people_rows,
        "projects": open_projects(),
        "project_id": project_id,
        "today": today,
        "unassigned": next((entry for entry in people_rows if entry["person"] is None), None),
    })
