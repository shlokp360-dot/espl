"""
The Drawings repository: which drawings a site needs, which revision it holds,
and the same for every project already built.

>>> ANCHOR: DRAWINGS-MODEL <<<

FOUR TABLES, TWO OF THEM MASTERS:

    Architect           who draws — a master, shared by every project
    DrawingGroup        ARC · STR · SUR · PAS · MEP — the five types receivable,
                        seeded by `0003_five_types` (Architect, Structure,
                        Survey, Passing, MEP; Passing = the AMC-passed set)
    Drawing             one line on a project's register, by the ARCHITECT'S number
    DrawingRevision     the file itself — R0, R1, R2 — versioned, never overwritten

⚠ THE DRAWING NUMBER IS TYPED, NOT GENERATED. It is the architect's number — the
    one written in the title block and quoted on site — so it must be theirs and
    not ours. Unique per project, because two architects on two sites may well
    both call their first sheet A-101.

⚠ STATUS IS DERIVED, NEVER TYPED — see `status.py`. Required means no revision
    has arrived; Received means the newest one has not been approved; Approved
    means it has. A newer revision arriving after an approved one puts the
    drawing back to Received, because the paper on site is no longer the paper
    that was approved.

⚠ NOTHING IS OVERWRITTEN AND NOTHING IS DELETED. A revision is a NEW ROW; R0
    stays downloadable after R1 arrives, because the day a wall is in the wrong
    place the question is "which revision was on site", and the answer must be
    on file. A drawing with revisions can only be deactivated.

⚠ A COMPLETED PROJECT KEEPS ITS REGISTER AND STILL ACCEPTS FILES. The owner's
    words: a repository "where I can add drawings and compliance data of
    previous projects". Won and Completed are both live here; only Draft,
    Quoted and Lost have no register.

⚠ THERE IS NO TRANSMITTAL. Who was handed which revision is not recorded —
    "no requirement of transmittal, just revisions" (11 Sep 2026). The
    `Transmittal`/`TransmittalLine` tables were dropped by `0004_drop_transmittals`.
"""
from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

# Copied from masters.models rather than imported: a validator is a value baked
# into migrations, and a master's rule must not change under this app's feet.
digits_only = RegexValidator(r"^\d*$", "Digits only — no spaces, plus signs or dashes.")


class Architect(models.Model):
    """Who draws. A master shared by every project — most sites share one firm."""

    name = models.CharField(max_length=120)
    firm = models.CharField(max_length=160, blank=True)
    phone = models.CharField(max_length=15, blank=True, validators=[digits_only])
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.firm})" if self.firm else self.name


class DrawingGroup(models.Model):
    """The register's sections — Architect, Structure, Survey, Passing, MEP."""

    code = models.CharField(max_length=4, unique=True,
                            help_text="Up to four capitals, e.g. ARC. Shown on the register.")
    name = models.CharField(max_length=80)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "code"]

    def __str__(self):
        return f"{self.code} — {self.name}"

    def clean(self):
        self.code = (self.code or "").strip().upper()
        self.name = (self.name or "").strip()


class DrawingInUse(Exception):
    """Raised when something tries to delete a drawing that has a history."""


class Drawing(models.Model):
    """One line on a project's register, identified by the architect's number."""

    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT,
                                related_name="drawings")
    group = models.ForeignKey(DrawingGroup, on_delete=models.PROTECT, related_name="drawings")
    number = models.CharField(max_length=40, help_text="The architect's drawing number, as printed.")
    title = models.CharField(max_length=200)
    architect = models.ForeignKey(Architect, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name="drawings")
    required_by = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="drawings_registered")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["group__sort_order", "group__code", "number"]
        constraints = [
            models.UniqueConstraint(fields=["project", "number"], name="one_drawing_number_per_project"),
        ]

    def __str__(self):
        return f"{self.number} — {self.title}"

    @property
    def latest_revision(self):
        """The current revision, or None. One query — use `status.latest_by_drawing` for lists."""
        return self.revisions.order_by("-uploaded_at", "-id").first()

    @property
    def status(self):
        """Derived from the newest revision. Never stored — see `status.py`."""
        from drawings import status as drawing_status
        return drawing_status.status_of(self.latest_revision)

    def delete(self, *args, **kwargs):
        """
        >>> ANCHOR: DRAWINGS-NO-DELETE <<<
        ⚠⚠ REFUSED ONCE A REVISION EXISTS. The revision FK cascades at the
           database, so this guard is the only thing standing between a stray
           delete and a file that was on site quietly leaving the repository.
           A drawing with a history is deactivated.
        """
        if self.revisions.exists():
            raise DrawingInUse(
                f"{self.number} has revisions on file and cannot be deleted. Deactivate it instead.")
        return super().delete(*args, **kwargs)


class DrawingRevision(models.Model):
    """
    One file, one revision label. The newest row for a drawing is the current one.

    ⚠ VERSIONED BY EXISTENCE, NOT BY A FLAG. There is no `is_current` to fall out
      of step; the newest row wins, and every earlier row stays downloadable.

    ⚠ NEVER SERVED FROM A URL. The file sits under MEDIA_ROOT with no MEDIA_URL,
      and is read back only through `views.download` after the permission check.
    """

    drawing = models.ForeignKey(Drawing, on_delete=models.CASCADE, related_name="revisions")
    label = models.CharField(max_length=12, help_text="As the architect labels it — R0, R1, R2.")
    file = models.FileField(upload_to="drawings/%Y/%m/")
    original_name = models.CharField(max_length=200)
    size_bytes = models.PositiveIntegerField(default=0)
    received_on = models.DateField(default=timezone.localdate)
    note = models.CharField(max_length=300, blank=True)

    approved_on = models.DateField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="drawing_approvals")

    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="drawing_uploads")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["drawing", "label"], name="one_label_per_drawing"),
        ]
        indexes = [models.Index(fields=["drawing", "-uploaded_at"])]

    def __str__(self):
        return f"{self.drawing.number} {self.label}"

    @property
    def is_approved(self):
        return self.approved_on is not None

    def approve(self, user, on=None):
        """
        >>> ANCHOR: DRAWINGS-APPROVE-ONCE <<<
        ⚠ RECORDS WHO AND WHEN, AND REFUSES A SECOND TIME. An approval is a fact
          about a moment; re-approving would silently move the date and the name
          onto somebody else, and the first approver's signature would be gone.
        """
        if self.approved_on is not None:
            raise ValueError(
                f"{self} was already approved on {self.approved_on:%d/%m/%Y}"
                + (f" by {self.approved_by.get_full_name() or self.approved_by.username}"
                   if self.approved_by else "") + ".")
        self.approved_on = on or timezone.localdate()
        self.approved_by = user
        self.save(update_fields=["approved_on", "approved_by"])
