"""
Projects, the ACTIVITY MASTER, and the BOQ estimator (Steps 1 and 2).

WHAT THIS FILE IS FOR
    * Activity  — the company-wide list of trades. THE single source of truth.
    * Project   — one job.
    * Estimate  — the BOQ for that job.
    * MaterialActivity — which activities offer which materials.

WHAT DEPENDS ON IT
    Almost everything. Material codes start with an Activity abbreviation, the
    BOM is grouped by Activity, and each activity's reserve comes from its
    estimate line. Changing Activity has a wide blast radius — read the anchors.

THE BOQ METHOD
    line amount = rate x BUA
    base        = sum of line amounts          <-- EX-GST. This matters, see below.
    total       = (base + contingency + design fee) + GST

    >>> ANCHOR: BOM-CALC-GST-BASIS <<<
    GST IS ADDED ONCE, AT THE END, TO THE WHOLE ESTIMATE.
    So a trade's amount (rate x BUA) is a PRE-GST figure, and that same figure
    becomes the activity's budget reserve on the BOM. Every BOM comparison —
    planned, used, variance — must therefore ALSO be ex-GST, or you are
    comparing a price against a price-plus-tax.
    This was got wrong once: it reported RCC at 99.3% of budget when the true
    figure was 84.2%. See PROJECT-CONTEXT.md, 5 Aug 2026.

AGREED BEHAVIOUR — see PROJECT-CONTEXT.md before changing any of it:
  * Admin-only. No approval workflow on estimates.
  * NO VERSIONING. An estimate is a working document, not a contract.
  * Rates pre-fill from the Activity master; edits apply to that project only.
  * Activities can be REMOVED from a project (that deselects them — the master
    row is never deleted) but can only be ADDED by picking from the master.
    No free-text parameters typed onto a project.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models


# ⚠ `Activity` AND `activity_abbreviation` MOVED TO `masters` IN SLICE 8.
#
#   They are master data — the trade list the BOQ picks from, that materials and
#   vendors both point at — and they now sit beside MaterialGroup and VendorGroup
#   where the rest of the master data lives. Saahil's call, and it resolved a
#   layering problem rather than creating one: once a material names its trade,
#   `masters` genuinely needs an activity, and having it in `projects` would have
#   meant masters importing from projects.
#
#   The table is STILL `projects_activity` and was deliberately not renamed —
#   see the Meta on masters.Activity for why.
#
#   Imported below only so that this module can still reference it. Anything
#   NEW should import it from masters.models directly.
from masters.models import Activity  # noqa: F401  (re-exported; see the note above)


class MaterialActivity(models.Model):
    """
    WHICH ACTIVITIES OFFER WHICH MATERIALS. Many-to-many, on purpose.

    Cement is used in RCC, Masonry AND Plaster. Steel in RCC and Fabrication.

    >>> ANCHOR: BOM-MATERIAL-FILTER <<<
    THIS TABLE — never the material's code — decides what a BOM dropdown shows.
    The code carries only the material's HOME activity, which is where it lives,
    not where it may be used. Read a code to filter and you will be wrong the
    moment a material is reclassified.

    Filtering, never restricting: inside RCC the dropdown offers RCC materials
    first, with a switch to search everything.

    It lives in this app rather than `masters` so the dependency runs one way:
    projects knows about masters, masters knows nothing about projects.
    """
    material = models.ForeignKey("masters.Material", on_delete=models.CASCADE,
                                related_name="activity_links")
    activity = models.ForeignKey(Activity, on_delete=models.PROTECT,
                                 related_name="material_links")

    # Exactly one home per material — the one whose abbreviation is in its code.
    is_home = models.BooleanField(
        default=False,
        help_text="The activity this material belongs to. Its abbreviation is in the material's code.",
    )

    class Meta:
        unique_together = [("material", "activity")]
        verbose_name_plural = "material activities"
        ordering = ["material", "activity"]

    def __str__(self) -> str:
        return f"{self.material.code} · {self.activity.abbreviation}{' (home)' if self.is_home else ''}"


class Project(models.Model):
    """
    One job.

    ⚠ A PROJECT IS NEVER DELETED once work has happened against it. A goods
    receipt protects its purchase-order line, which protects the order, which
    protects the project — the database refuses, all the way up the chain. That
    is correct (material that arrived on site is not a mistake you can erase)
    but it means finished jobs pile up forever.

    Saahil's answer, 9 Aug 2026: don't fight the database, filter the list.
    A project is marked COMPLETED when the work is done and drops out of the
    default view. Nothing is hidden — "All projects" still shows everything —
    and nothing is destroyed.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        QUOTED = "quoted", "Quoted"
        WON = "won", "Won"
        # Won means "sold". COMPLETED means "the building is finished". They are
        # different facts about different things, which is why Won could not
        # simply be reused: a project is Won for the whole time it is being
        # built, which is exactly when it is most active.
        COMPLETED = "completed", "Completed"
        LOST = "lost", "Lost"

    # Still live and worth looking at. Everything else is history.
    ONGOING = [Status.DRAFT, Status.QUOTED, Status.WON]

    # >>> ANCHOR: CODE-GEN <<<
    # ⚠ ASSIGNED BY THE SYSTEM, NEVER TYPED. Saahil's call, and the same rule
    #   that already governs materials, vendors and purchase orders: a code is an
    #   IDENTITY, handed out once and never reused.
    #
    #   The alternative — letting somebody type PRJ-BHUD because it reads better
    #   — was considered and rejected. Two people invent two schemes within a
    #   month, and a typo becomes permanent, because a code that other records
    #   point at can never be corrected afterwards.
    #
    #   Blank on a new project until save() fills it in. See next_project_code().
    code = models.CharField(max_length=12, unique=True, blank=True,
                            help_text="Assigned automatically, e.g. PRJ-000001. Never typed.")
    name = models.CharField(max_length=200)
    location = models.CharField(max_length=200, blank=True)
    bua_sqft = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(1)],
                                   help_text="Built-up area including common areas, staircase, lift lobby and mumty")
    floors = models.CharField(max_length=20, blank=True, help_text="e.g. G+7. Recorded, but does not affect the rate today.")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)

    # >>> ANCHOR: PROJECT-ADDRESSES <<<
    # TWO ADDRESSES, AND THEY ARE GENUINELY DIFFERENT. Saahil's point, 10 Aug:
    # the invoice goes to the office, the material goes to the site. Their own
    # work orders already carry a "Work Billed To" line, so the distinction
    # exists in the business today. A purchase order therefore prints four
    # blocks: FROM (us) · TO (the vendor) · BILL TO · SHIP TO.
    #
    # ⚠ ADDRESSES ONLY — NO GSTIN HERE, DELIBERATELY. Confirmed 10 Aug: a vendor
    #   writes the same 15-digit GSTIN on every invoice whatever the project, so
    #   there is one registration and the CGST+SGST vs IGST decision keeps
    #   comparing the vendor's state with the COMPANY's.
    #
    #   If that ever changes — a second state registration, or a project run
    #   under its own entity — this is where a billing_gstin would go, and
    #   po_service would read it instead of CompanyProfile. It also drags in the
    #   GST "bill to / ship to" place-of-supply rules, which are a question for
    #   Saahil's CA and must not be guessed at here.
    billing_address = models.TextField(
        blank=True, help_text="Where the vendor's invoice goes. Prints as BILL TO.")
    site_address = models.TextField(
        blank=True, help_text="Where material is delivered. Prints as SHIP TO, and pre-fills "
                              "the delivery address on every order for this project.")

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   null=True, blank=True, related_name="projects")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

    def save(self, *args, **kwargs):
        """
        Give a new project its code, once.

        >>> ANCHOR: CODE-GEN <<<
        ⚠ ONLY WHEN IT HAS NONE. An existing project keeps the code it was given
          — a purchase order, a BOM and a receipt all point at it, and a code
          that changes underneath them stops being an identity.

        The counter only ever climbs, so a deleted project leaves a gap and the
        number is never handed out twice. Same NumberSeries that stopped purchase
        orders reusing numbers after a delete — which was a real bug, found by a
        test, not by reading the code.
        """
        if not self.code:
            self.code = next_project_code()
        super().save(*args, **kwargs)


def next_project_code():
    """PRJ-000001, PRJ-000002, … Six digits is padding, not a ceiling."""
    from .bom_models import NumberSeries
    return f"PRJ-{NumberSeries.take_next('project'):06d}"


class Estimate(models.Model):
    """
    One estimate per project. Edited in place — deliberately not versioned.

    >>> ANCHOR: BOQ-LOCK <<<
    ⚠ IT STOPS BEING EDITABLE THE MOMENT THE PROJECT IS WON. Saahil's rule,
      10 Aug: *"once a project draft is won, it is not editable, as we can see
      that in reserves"*.

    WHY IT MATTERS MORE THAN IT LOOKS
        An activity's reserve is a LIVE LINK to its estimate line — rate × BUA,
        read fresh every time — so editing a rate here moves the budget that the
        site team's spend is measured against. That was flagged as a governance
        risk when the live link was chosen on 4 Aug and accepted at the time.
        This closes it: the reserve becomes a fixed number exactly when people
        start being judged on it.

    ⚠ NO EXCEPTIONS, INCLUDING ADMIN. Saahil was explicit. The consequence,
      recorded rather than hidden: a rate typed wrong before Won cannot be
      corrected on that project, and the BOM will be measured against a figure
      everybody knows is wrong.

      The one pressure valve, which exists whether or not it is designed: put
      the project back to Quoted, fix the rate, set it to Won again. That is
      deliberately not blocked — it leaves a visible trace on the project, which
      is far better than a silent correction nobody can see.
    """
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="estimate")

    contingency_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("4.00"))
    design_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("5.00"))
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("18.00"))

    saved_at = models.DateTimeField(null=True, blank=True,
                                    help_text="Exports always use the last saved state.")
    updated_at = models.DateTimeField(auto_now=True)

    # ---- the lock -----------------------------------------------------
    #
    # Draft and Quoted are the selling phase: the number is still being argued
    # about. Won means the client has accepted it, and from that moment the
    # reserve is what the site is measured against. Completed and Lost are
    # history, and history does not get edited either.
    EDITABLE_WHILE = [Project.Status.DRAFT, Project.Status.QUOTED]

    @property
    def is_editable(self) -> bool:
        return self.project.status in self.EDITABLE_WHILE

    @property
    def locked_reason(self) -> str:
        """Why it is locked, in words a person can act on. Empty when it is not."""
        if self.is_editable:
            return ""
        return (f"This BOQ locked when {self.project.code} became "
                f"{self.project.get_status_display()}. Its rates are now the budget every "
                f"purchase is measured against, so they no longer move. To change one, put the "
                f"project back to Quoted first — which leaves a visible trace that somebody did.")

    # ---- calculations -------------------------------------------------
    @property
    def composite_rate(self) -> Decimal:
        """
        Every trade's rate added up — the ₹/sqft this project quotes at.

        ⚠ `_composite` IS A ONE-PASS HANDOVER, NOT A CACHE. boq_rows() sets it
          after loading the lines once, because otherwise every line asking for
          its share re-runs this query and an 18-trade estimate costs 38 extra
          queries — measured, and caught by the sweep.

          It lives on one in-memory object for the length of one request and is
          never written anywhere, so there is nothing that can go stale. Same
          arrangement as bom_calc handing its three sums down, and the same
          reason it is not the forbidden kind of caching.
        """
        cached = getattr(self, "_composite", None)
        if cached is not None:
            return cached
        return sum((ln.rate for ln in self.lines.all()), Decimal("0"))

    @property
    def base_cost(self) -> Decimal:
        return self.composite_rate * self.project.bua_sqft

    @property
    def contingency_amount(self) -> Decimal:
        return self.base_cost * self.contingency_percent / 100

    @property
    def design_fee_amount(self) -> Decimal:
        return self.base_cost * self.design_fee_percent / 100

    @property
    def cost_before_gst(self) -> Decimal:
        return self.base_cost + self.contingency_amount + self.design_fee_amount

    @property
    def gst_amount(self) -> Decimal:
        return self.cost_before_gst * self.gst_percent / 100

    @property
    def grand_total(self) -> Decimal:
        return self.cost_before_gst + self.gst_amount

    @property
    def cost_per_sqft(self) -> Decimal:
        bua = self.project.bua_sqft
        return self.grand_total / bua if bua else Decimal("0")

    # ---- what each add-on is as a share of what the client is billed -------
    #
    # >>> ANCHOR: BOQ-LIVE-KPIS <<<
    # ⚠ POINT 9. The KPI cards' grey sub-text used to restate the percentage
    #   typed in the box below it — "5% of base" under a field containing 5 —
    #   which earns no space at all, and earns less now that the two move
    #   together as you type. The share of the GRAND TOTAL is a different
    #   number and the one people argue about: 8% contingency is 6.4% of what
    #   the client is billed, because the percentages compound and GST sits on
    #   top of all of it.
    #
    # ⚠ AGAINST THE GRAND TOTAL, NOT THE BASE. Against the base they would just
    #   be the typed figures again.

    def _share(self, amount) -> Decimal:
        total = self.grand_total
        return (amount * 100 / total) if total else Decimal("0")

    @property
    def contingency_share(self) -> Decimal:
        return self._share(self.contingency_amount)

    @property
    def design_fee_share(self) -> Decimal:
        return self._share(self.design_fee_amount)

    @property
    def gst_share(self) -> Decimal:
        return self._share(self.gst_amount)

    def __str__(self) -> str:
        return f"Estimate for {self.project.code}"


class EstimateLine(models.Model):
    """
    One activity selected onto one project's estimate.

    The name, rate and basis are COPIED from the Activity master when the line
    is created, then editable for this project only. Editing here never touches
    the master.

    >>> ANCHOR: BOM-CALC-RESERVE <<<
    This line's `amount` (rate x BUA) becomes that activity's budget reserve on
    the BOM — and it is a LIVE LINK, not a copy. Saahil's call, against advice:
    a reserve should show the CURRENT budget, so editing the estimate moves it.
    This is the ONE documented exception to copy-don't-link in the whole system;
    BOM and PO line prices still take frozen copies. Consequence to keep in
    mind: whoever edits the estimate can move the number the site team is
    measured against, so editing a saved BOQ must warn about exactly that.
    """
    estimate = models.ForeignKey(Estimate, on_delete=models.CASCADE, related_name="lines")
    name = models.CharField(max_length=120)
    rate = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=18)
    basis = models.CharField(max_length=300, blank=True)
    is_custom = models.BooleanField(default=False, help_text="Added for this project, not from the company defaults")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    @property
    def amount(self) -> Decimal:
        return self.rate * self.estimate.project.bua_sqft

    @property
    def share(self) -> Decimal:
        """
        This trade's slice of the quote, as a fraction.

        Rate over composite rate — the BUA cancels out, so it is the same answer
        as amount over base cost with one less multiplication. Shown as a
        percentage on the screen, which is where a rate that is wrong by a factor
        of ten becomes obvious: RCC at 4% of a building is not a typing error
        anybody spots in a column of rupees.
        """
        composite = self.estimate.composite_rate
        return (self.rate / composite) if composite else Decimal("0")

    def __str__(self) -> str:
        return f"{self.name} — ₹{self.rate}/sqft"

# ---------------------------------------------------------------------------
# The BOM, purchase orders and receipts live in bom_models.py to keep this file
# readable. Imported here so Django registers them and `from projects.models
# import Bom` keeps working.
# ---------------------------------------------------------------------------
from .bom_models import (  # noqa: E402,F401  (imported for registration)
    Bom, BomLine, NumberSeries, PurchaseOrder, PurchaseOrderLine, Receipt,
)
