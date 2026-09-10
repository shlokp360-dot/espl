"""
The compliance repository: what every project must hold, and what it holds.

>>> ANCHOR: COMPLIANCE-MODEL <<<

⚠ AMC IS THE AHMEDABAD MUNICIPAL CORPORATION, not annual maintenance contracts.
    That question was asked before a line was designed, and the answer changed
    the content of every checklist item while leaving the structure identical.

FOUR LEVELS, AND THE MIDDLE ONE IS HIS WORD:

    ComplianceType      AMC · RERA          "there is an AMC compliance which is
                                             compulsory, and then there is an
                                             RERA compliance which is optional"
    ComplianceTitle     the "title or sub header" — Plan passing, Commencement
    ComplianceItem      the line item — Rajachitthi, Plinth checking
    ComplianceDocument  the paper itself, versioned, never overwritten

⚠ THE CHECKLIST IS STANDARD AND THE DOCUMENTS ARE PER PROJECT. One master, used
    by every project the type applies to. Adding an item makes it Missing
    everywhere at once, which is correct for a new municipal requirement and is
    exactly why the item dialog states that before saving.

⚠ NOTHING IS OVERWRITTEN AND NOTHING IS DELETED. A new upload is a NEW VERSION;
    the old one stays and stays downloadable, because the superseded one is often
    the one an inspector asks about. A master item with documents can only be
    deactivated. This is an evidence trail somebody may be asked to produce years
    later.

⚠ STATUS IS DERIVED, NEVER TYPED — see `status.py`. Nobody maintains a status
    field, so nothing can quietly disagree with reality. The same principle as
    delay days being computed rather than declared.

⚠ EXPIRY IS TYPED, NOT READ FROM THE PDF. Saahil asked whether the code could
    extract it; it could, and it should not. Municipal documents vary wildly,
    many are scans needing OCR, it adds two dependencies to a project that
    installs three, and **a silently wrong expiry is worse than a blank one**.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class ComplianceType(models.Model):
    """
    A regime — AMC, RERA, and whatever a lender or a fire department demands next.

    ⚠ `applies_to_every_project` IS THE WHOLE DIFFERENCE BETWEEN AMC AND RERA,
      and making it a field rather than a hardcoded rule is what lets a new
      regime arrive without a code change: *"RERA is for private projects, we can
      have a tick when the project is being made"*.
    """

    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=120)
    applies_to_every_project = models.BooleanField(
        default=True,
        help_text="On for a regime nobody can opt out of. Off for one that is ticked per project.")
    note = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "code"]

    def __str__(self):
        return f"{self.code} — {self.name}"


class ComplianceTitle(models.Model):
    """The sub-header a group of documents sits under."""

    type = models.ForeignKey(ComplianceType, on_delete=models.PROTECT, related_name="titles")
    name = models.CharField(max_length=120)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["type", "name"], name="one_title_name_per_type"),
        ]

    def __str__(self):
        return f"{self.type.code} · {self.name}"


class Kind(models.TextChoices):
    """
    How a line item behaves over time.

    ⚠ `REPEAT` WAS INVENTED FOR RERA'S QUARTERLY FILINGS AND IS FLAGGED IN
      `OPEN-BEFORE-GO-LIVE.md` AS UNCONFIRMED. Without it, Forms 1/2/3 would read
      "Held" forever after one upload, which is worse than an odd third kind. The
      alternative — a 90-day validity — works and reads oddly.
    """

    ONE = "one", "One time"
    VALID = "valid", "Has a validity"
    REPEAT = "repeat", "Due again each quarter"


class ComplianceItem(models.Model):
    """One line on the checklist — the thing a document is held against."""

    title = models.ForeignKey(ComplianceTitle, on_delete=models.PROTECT, related_name="items")
    name = models.CharField(max_length=160)
    # ⚠ NULL MEANS EVERY PROJECT, WHICH IS THE NORMAL CASE. A value means this
    #   line exists on ONE site — a lake-margin NOC, a condition attached to one
    #   plot. Saahil asked for both and both are real: a new municipal rule must
    #   land everywhere at once, and a one-off condition must not.
    #
    #   The screens say which is which, because an item that appears on one
    #   project and not another is otherwise indistinguishable from a bug.
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE,
                                null=True, blank=True, related_name="own_compliance_items",
                                help_text="Leave empty for every project. Set it for a "
                                          "requirement that applies to one site only.")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.ONE)
    # ⚠ Used only as a SUGGESTION on the upload form when the kind is VALID. The
    #   expiry that counts is the one typed against the document, because the
    #   paper says what the paper says.
    validity_days = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Typical validity, used to suggest an expiry date. The typed date wins.")
    is_compulsory = models.BooleanField(
        default=True, help_text="Off for a document that is good practice rather than required.")
    note = models.CharField(max_length=300, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [
            # ⚠ SCOPED BY PROJECT. "Fire NOC" may exist once for everybody and
            #   once more for one site with different wording; what must not
            #   happen is the same line twice in the same scope.
            models.UniqueConstraint(fields=["title", "name"], condition=models.Q(project=None),
                                    name="one_global_item_name_per_title"),
            models.UniqueConstraint(fields=["title", "name", "project"],
                                    name="one_project_item_name_per_title"),
        ]

    def __str__(self):
        return self.name


class ProjectCompliance(models.Model):
    """
    Whether an optional regime applies to one project.

    ⚠ A ROW EXISTS ONLY FOR A TYPE SOMEBODY HAS DECIDED ABOUT. A type that
      applies to every project needs no row at all — `applies_to(project, type)`
      answers from the type itself, so a compulsory regime cannot be switched off
      by forgetting to create something.
    """

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE,
                                related_name="compliance_types")
    type = models.ForeignKey(ComplianceType, on_delete=models.PROTECT,
                             related_name="project_rows")
    applicable = models.BooleanField(default=True)
    decided_at = models.DateTimeField(auto_now=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="compliance_decisions")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "type"], name="one_row_per_project_type"),
        ]

    def __str__(self):
        return f"{self.project.code} · {self.type.code}: {'yes' if self.applicable else 'no'}"


def applies_to(project, type):
    """Whether a regime applies to a project — the one place that is decided."""
    if type.applies_to_every_project:
        return True
    row = ProjectCompliance.objects.filter(project=project, type=type).first()
    return bool(row and row.applicable)


class ProjectComplianceItem(models.Model):
    """
    A checklist line this project does NOT need.

    >>> ANCHOR: COMPLIANCE-PRUNING <<<
    ⚠⚠ THE SECOND LEVEL, AND THE FIRST ONE IS UNTOUCHED. `ProjectCompliance`
       above decides whether a whole REGIME applies — RERA yes, AMC always — and
       Saahil was explicit that it stays exactly as it is: "I like that option of
       RERA applicable or any other compliance of applicable, and then based on
       that checkbox, it loads at the bottom. So please keep that." This model
       works one level down, on individual LINES inside a regime that already
       applies.

       Before it there were only two states: an item belonged to every project,
       or to exactly one. So "not applicable to THIS site" could only be said by
       deactivating the line in the master, which removed it from every project
       at once — which is precisely what he hit: "I removed something and it
       disappeared from every project."

    ⚠⚠ IT RECORDS WHAT WAS REMOVED, NOT WHAT WAS SELECTED, and that is the whole
       design. He described the shape as the BOQ's "add ticked trades", which is
       a selection; but every behaviour he asked for is the opposite of one:

         "the project starts full and is pruned"   -> no rows means everything
         "a new master line lands on every         -> nothing to write; absence
          existing project"                           already means included
         "removing a line removes it from that     -> one row, on one project
          project only"

       A selection table would need every project x every line written on
       migration, and a fan-out write to every live site each time the master
       gains a line — the exact operation that can silently miss a project. This
       one cannot: to be missed, a row would have to be created by mistake.

    ⚠ REMOVAL IS REFUSED WHILE THE LINE HOLDS DOCUMENTS. Enforced in the view
      with the count in the message, because it must never orphan filed paper.
      Removal is for lines that were never applicable to the site, which is his
      actual case.

    ⚠ NOTHING IS GREYED OUT. Claude proposed keeping a removed line visible and
      marked "not applicable", on the same reasoning that vendors are deactivated
      rather than deleted. He rejected it — "if we just make it not applicable,
      then it may fill up a lot of space as well" — and he was right: a project
      showing 21 AMC lines of which 8 are noise is worse than one showing the 13
      that matter. Removed means gone from the screen. The row here is the record.
    """

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE,
                                related_name="removed_compliance_items")
    item = models.ForeignKey(ComplianceItem, on_delete=models.CASCADE,
                             related_name="removed_from_projects")
    removed_at = models.DateTimeField(auto_now_add=True)
    removed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="compliance_removals")
    reason = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "item"],
                                    name="one_removal_per_project_item"),
        ]
        ordering = ["item__sort_order", "item__name"]

    def __str__(self):
        return f"{self.project.code} does not need {self.item.name}"


def removed_item_ids(project):
    """
    The checklist lines this project has pruned. One query, as a set of ids.

    ⚠ ASKED ONCE PER SCREEN, NOT ONCE PER LINE — the Overview walks every Won
      project against every regime, so a lookup per row is the shape of bugs 3
      and 9 all over again.
    """
    if project is None:
        return set()
    return set(ProjectComplianceItem.objects
               .filter(project=project).values_list("item_id", flat=True))


def compliance_document_path(instance, filename):
    """
    Where a file lands: media/compliance/PRJ-000001/<item id>/<filename>.

    ⚠ NEVER SERVED FROM A URL. These sit outside the static tree and are read
      back through a permission-checked view — a signed municipal approval must
      not be readable by anybody holding a link.
    """
    return f"compliance/{instance.project.code}/{instance.item_id}/{filename}"


class ComplianceDocument(models.Model):
    """
    One piece of paper, held against one item on one project.

    ⚠ VERSIONED BY EXISTENCE, NOT BY A FLAG. The newest row for a project+item is
      the current one; every earlier row stays exactly as it was and stays
      downloadable. There is no "is_current" to fall out of step.

    ⚠ `FileField`, NOT `ImageField` — an ImageField needs Pillow, and CI installs
      Django, python-dotenv and openpyxl. That objection killed task photos; it
      does not apply here and was not carried over by habit.
    """

    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT,
                                related_name="compliance_documents")
    item = models.ForeignKey(ComplianceItem, on_delete=models.PROTECT, related_name="documents")

    file = models.FileField(upload_to=compliance_document_path)
    original_name = models.CharField(max_length=200)
    size_bytes = models.PositiveIntegerField(default=0)

    reference = models.CharField(max_length=120, blank=True,
                                 help_text="The number on the document, if it has one.")
    issued_on = models.DateField(null=True, blank=True)
    # ⚠ TYPED. See the note at the top of this file.
    expires_on = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)

    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="compliance_uploads")

    # ⚠ A CORRECTION IS NOT AN UPLOAD, AND IS RECORDED SEPARATELY. Two different
    #   things hide under "change an approval": the PAPER is superseded, which is
    #   a new version — or the TYPING beside it was wrong, which is this. Fixing
    #   a mistyped expiry by re-uploading the same document would leave two
    #   identical files on record and make the version history a lie.
    corrected_at = models.DateTimeField(null=True, blank=True)
    corrected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name="compliance_corrections")

    class Meta:
        ordering = ["-uploaded_at", "-id"]
        indexes = [models.Index(fields=["project", "item", "-uploaded_at"])]

    def __str__(self):
        return f"{self.item.name} — {self.project.code}"

    @property
    def days_to_expiry(self):
        """Negative once it has expired. None for anything without a validity."""
        if self.expires_on is None:
            return None
        return (self.expires_on - timezone.localdate()).days
