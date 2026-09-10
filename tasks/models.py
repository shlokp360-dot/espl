"""
Work to be done on a site: header tasks, the subtasks under them, and milestones.

>>> ANCHOR: TASK-MODEL <<<

WHAT THIS IS
    "Earthing" is a header task; "Dig earth pits" is a subtask with a person and
    a date against it. Saahil's own words: "Earthing will be header task with a
    project manager assigned, and the other sub tasks below it will have assigned
    user or users, planned time … and mark as completed or not."

⚠ ONE LEVEL OF SUBTASK AND NO MORE. Two levels is a task list; three is a
    project plan, and nobody maintains a project plan.

⚠ TASKS ARE DESCRIPTIONS, NOT MATERIALS — "the task are descriptions and not
    materials". Nothing here points at a BOM line, a material or a purchase
    order. Quantities and money stay where they already are.

⚠ EVERY HEADER TASK NAMES AN ACTIVITY, AND IT IS A FOREIGN KEY.
    The name is typed ad hoc — "the header task can be adhocly created by the
    project manager/admin" — but the classification comes from the activity
    master. That link is what will eventually let the system say "Electrical is
    three days behind and 84% of its budget is committed".

    ⚠⚠ BY ID, NEVER BY NAME. The BOQ reserve matches activities by NAME and that
      is a known landmine: renaming an activity would silently orphan every line
      that copied the old text. This is the same relationship done properly, and
      it costs nothing to get right on day one.

⚠ ONLY WON PROJECTS CARRY TASKS — "have a project input option filtered from won
    projects". A quoted job has no site to work on, and the BOQ locks at Won,
    which is the same moment the work becomes real. The screens filter; nothing
    in the database stops a task being attached to a project that is later lost.

⚠ DATES: A START AND A DURATION IN DAYS. THE FINISH IS COMPUTED, NEVER TYPED.
    Saahil: "duration works, but keep it in days, and we can add a start date of
    the task or something to use it as reference to plot accurate gantt chart".
    Both levels carry both, and they mean different things:

        the header's    = the commitment the manager made, before the detail
                          existed. Without it a header with no subtasks yet has
                          no dates and no bar at all.
        the subtasks'   = the working plan.

    The gap between them is an early warning — "the subtasks already run past
    what I promised" — which arrives before anything is actually late.

    ⚠ THIS REVERSED AN EARLIER DECISION ("a parent's dates derive from its
      children, nobody types them"). It is the later decision and it stands.
"""
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


def _end(start, days):
    """
    The finish, from a start and a duration.

    ⚠ INCLUSIVE OF DAY ONE. A task starting Monday for 3 days finishes
      Wednesday, not Thursday — which is how anybody on a site would say it.
    """
    return start + timedelta(days=max(1, days) - 1)


def finish(start, days):
    """
    The same sum, named for use OUTSIDE this module.

    ⚠ THE SCREENS MUST NOT HAVE THEIR OWN COPY OF THIS. A view working out a
      finish date by hand is a second definition of "three days from Monday",
      and one of the two will eventually forget that day one counts.
    """
    return _end(start, days)


class DelayReason(models.TextChoices):
    """
    ⚠ A FIXED LIST, AND THAT IS THE WHOLE POINT.

    Free text says more about one delay; a list can be COUNTED across a year.
    "Which of these actually holds our sites up" is the question the delay log
    exists to answer, and free text cannot answer it. A one-line note is
    available beside it for the detail that does not fit.
    """

    MATERIAL = "material", "Material not delivered"
    TRADE = "trade", "Waiting on another trade"
    WEATHER = "weather", "Weather"
    LABOUR = "labour", "Labour short"
    DECISION = "decision", "Decision needed"
    ACCESS = "access", "Access not available"
    # ⚠ THE SEVENTH, ADDED WHEN RESCHEDULING WAS BUILT AND FLAGGED AS AN ADDITION
    #   TO THE AGREED SIX. A plan that moves because the drawing changed is not
    #   any of the six above, and without a word for it people will pick
    #   "Decision needed" and the count stops meaning anything.
    SCOPE = "scope", "Scope or design changed"


def _promised_end(obj):
    """
    The first finish ever committed to — the baseline.

    ⚠ CAPTURED THE FIRST TIME THE DATES MOVE, AND NEVER AGAIN. Saahil's call:
      rescheduling must not be able to make a late job look on time. The team
      works to the current plan; lateness is still readable against the promise.
    """
    if obj.original_start and obj.original_days:
        return _end(obj.original_start, obj.original_days)
    return obj.planned_end


def capture_promise(obj, new_start, new_days):
    """
    Remember what was first promised, then let the plan move.

    Returns the number of days the FINISH moves outward — zero when the work is
    being pulled forward or only reshuffled, which is not a delay and must not
    be made to look like one.

    ⚠ THE FIRST VALUES ARE STORED ONLY ONCE. A plan pushed out three times in a
      row is three days of drift each time and one promise, not three.
    """
    was_end = _promised_end(obj)
    if obj.original_start is None:
        obj.original_start, obj.original_days = obj.start, obj.days
    obj.start, obj.days = new_start, new_days
    return max(0, (_end(new_start, new_days) - was_end).days)


class TaskHeader(models.Model):
    """A package of work on one site — "Earthing", "Slab shuttering"."""

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE,
                                related_name="task_headers")
    # ⚠ PROTECT: an activity with work booked against it must not vanish.
    activity = models.ForeignKey("masters.Activity", on_delete=models.PROTECT,
                                 related_name="task_headers")
    name = models.CharField(max_length=120)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                              null=True, blank=True, related_name="task_headers_owned")

    start = models.DateField(help_text="When the manager expects this work to begin.")
    days = models.PositiveIntegerField(
        default=7, help_text="Duration in days. The finish is worked out from this.")

    # >>> ANCHOR: TASK-BASELINE <<<
    # ⚠ WHAT WAS FIRST PROMISED, KEPT SO THAT MOVING THE PLAN CANNOT ERASE IT.
    #   Saahil's decision when rescheduling was added: "keep the first promise".
    #   Null on anything that has never been rescheduled, which is most of them —
    #   the promise IS the plan until somebody changes it.
    original_start = models.DateField(null=True, blank=True)
    original_days = models.PositiveIntegerField(null=True, blank=True)
    shift_reason = models.CharField(max_length=20, choices=DelayReason.choices, blank=True)
    shift_note = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="task_headers_created")

    class Meta:
        ordering = ["start", "id"]
        # ⚠ UNIQUE WITHIN A PROJECT, NOT ACROSS THEM. Saahil: "all task are
        #   unique" — but every site has an Earthing, so uniqueness that spanned
        #   projects would be wrong. The screen also refuses two that differ
        #   only by case.
        constraints = [
            models.UniqueConstraint(fields=["project", "name"], name="one_header_name_per_project"),
        ]

    def __str__(self):
        return f"{self.name} — {self.project.code}"

    # ---- dates -----------------------------------------------------------
    @property
    def planned_end(self):
        """What the manager committed to — the CURRENT plan, which may have moved."""
        return _end(self.start, self.days)

    @property
    def promised_end(self):
        """The FIRST finish committed to. The same as planned_end until it moves."""
        return _promised_end(self)

    @property
    def days_shifted(self):
        """How far the plan has been pushed beyond the original promise."""
        return max(0, (self.planned_end - self.promised_end).days)

    @property
    def was_rescheduled(self):
        return self.original_start is not None

    def work_span(self, subtasks=None):
        """
        What the subtasks actually add up to — earliest start, latest finish.

        Falls back to the header's own dates while there are no subtasks, which
        is exactly why the header carries dates of its own.
        """
        rows = list(self.subtasks.all()) if subtasks is None else list(subtasks)
        if not rows:
            return self.start, self.planned_end
        return (min(row.start for row in rows),
                max(row.finished_on or row.planned_end for row in rows))

    def days_over_plan(self, subtasks=None):
        """
        How far the subtasks run past the commitment. Zero when they do not.

        ⚠ THIS IS THE EARLY WARNING, and it is a different thing from a task
          being late. Nothing has slipped yet — the plan simply no longer fits
          inside what was promised, and that is visible before any date passes.
        """
        _start, end = self.work_span(subtasks)
        return max(0, (end - self.planned_end).days)

    def progress(self, subtasks=None):
        """`(done, total)` — never a typed percentage. Nobody estimates 40% honestly."""
        rows = list(self.subtasks.all()) if subtasks is None else list(subtasks)
        return sum(1 for row in rows if row.status == Subtask.Status.DONE), len(rows)


class Subtask(models.Model):
    """One person, one piece of work, one date."""

    class Status(models.TextChoices):
        OPEN = "open", "Not started"
        BLOCKED = "blocked", "Blocked"
        DONE = "done", "Done"

    class Priority(models.TextChoices):
        HIGH = "H", "High"
        NORMAL = "N", "Normal"
        LOW = "L", "Low"

    header = models.ForeignKey(TaskHeader, on_delete=models.CASCADE, related_name="subtasks")
    title = models.CharField(max_length=200, help_text="What needs doing, in their words.")
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name="subtasks")

    start = models.DateField()
    days = models.PositiveIntegerField(default=1)
    priority = models.CharField(max_length=1, choices=Priority.choices, default=Priority.NORMAL)

    # >>> ANCHOR: TASK-BASELINE <<<
    # ⚠ THE FIRST PROMISE, KEPT. See the same four fields on TaskHeader — a plan
    #   that moves must not be able to make a late job look on time.
    original_start = models.DateField(null=True, blank=True)
    original_days = models.PositiveIntegerField(null=True, blank=True)
    shift_reason = models.CharField(max_length=20, choices=DelayReason.choices, blank=True)
    shift_note = models.CharField(max_length=200, blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)

    # ⚠ THE PLANNED DATES ARE NEVER REWRITTEN WHEN SOMETHING SLIPS. If the
    #   assignee could move their own finish, nothing would ever be late and the
    #   schedule would become fiction inside a month. What happened is recorded
    #   beside what was planned, never on top of it.
    finished_on = models.DateField(null=True, blank=True)
    delay_reason = models.CharField(max_length=20, choices=DelayReason.choices, blank=True)
    delay_note = models.CharField(max_length=200, blank=True)

    blocked_reason = models.CharField(max_length=20, choices=DelayReason.choices, blank=True)
    blocked_note = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="subtasks_created")

    class Meta:
        ordering = ["start", "id"]

    def __str__(self):
        return self.title

    @property
    def planned_end(self):
        return _end(self.start, self.days)

    @property
    def promised_end(self):
        """The FIRST finish committed to. The same as planned_end until it moves."""
        return _promised_end(self)

    @property
    def days_shifted(self):
        """
        How far the plan has been pushed beyond the original promise.

        ⚠ A DIFFERENT COST FROM BEING LATE, AND BOTH ARE REAL. A job replanned
          twice and then delivered on the new date is not late — and it still
          finished a fortnight after it was first promised. The delay log counts
          the two separately and adds them up.
        """
        return max(0, (self.planned_end - self.promised_end).days)

    @property
    def was_rescheduled(self):
        return self.original_start is not None

    @property
    def days_late(self):
        """
        ⚠ COMPUTED, NEVER TYPED — Saahil: "recorded meaning, automatically
          captured, but the reason should be entered by the user." The number of
          days is arithmetic; only the reason needs a human.

        Zero for anything finished on time or early. Nobody justifies being early.
        """
        if not self.finished_on:
            return 0
        return max(0, (self.finished_on - self.planned_end).days)

    def days_overdue(self, today=None):
        """Open work that has run past its own finish. Different from days_late."""
        if self.status == self.Status.DONE:
            return 0
        today = today or timezone.localdate()
        return max(0, (today - self.planned_end).days)


# ⚠⚠ THE `Milestone` MODEL WAS DELETED HERE, AND ITS NAME MOVED TO TaskHeader.
#
#    Saahil, looking at the built board: "the customer, basically the admin,
#    wants to have milestone as phase one, phase two, phase three, which are
#    shown as a dotted line, and they keep on adding subtasks at the bottom. So
#    it's either milestone or head work… we can go ahead with head work, remove
#    the milestone, and then we change the name of head work to milestone."
#
#    He is describing one concept that had been built as two. A milestone here
#    carried a date somebody TYPED, sitting beside a header task whose finish
#    was COMPUTED from the work under it — so the two could disagree, and the
#    typed one would never find out. Everywhere else in this module a finish is
#    captured rather than declared; this was the exception, and removing it puts
#    the module back in step with itself.
#
#    A milestone is now a TaskHeader. Its date is the later of the promise and
#    the work actually done, so it moves when a task slips. The chart draws it
#    as a vertical dotted line — see ANCHOR: MILESTONE-LINE in schedule.py.
