"""
Materials Master and Vendor Master.

Design rules carried over from the data-cleaning work — do not change these
without reading PROJECT-CONTEXT.md first:

  * A material code is an IDENTITY, not a description. Auto-generated,
    never reused, never encodes size / grade / brand.
  * A vendor's identity is their PHONE NUMBER, not their name. Three names in
    the source data covered two different people each.
  * HSN and GST live on the MATERIAL (cement is HSN 2523 at 28% whoever sells
    it). The GSTIN lives on the VENDOR.
  * Phone numbers are stored as digits only. WhatsApp needs 91 + 10 digits.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import ProtectedError


UOM_CHOICES = [
    ("Nos", "Nos"), ("Set", "Set"), ("Pair", "Pair"), ("Bag", "Bag"),
    ("Packet", "Packet"), ("Box", "Box"), ("Tin", "Tin"), ("Bottle", "Bottle"),
    ("Bundle", "Bundle"), ("Drum", "Drum"), ("Kg", "Kg"), ("Ton", "Ton"),
    ("MT", "MT"), ("Litre", "Litre"), ("Metre", "Metre"), ("Rft", "Rft"),
    ("Sqft", "Sqft"), ("Sqm", "Sqm"), ("Cum", "Cum"), ("Tractor", "Tractor"),
    ("Trip", "Trip"), ("Job", "Job"), ("Hour", "Hour"), ("Day", "Day"),
    ("Month", "Month"), ("Lumpsum", "Lumpsum"), ("House", "House"),
    ("KW", "KW"),
]

# Spellings that appear in the spreadsheets but mean an existing unit.
#
# Kept as a translation table rather than adding each variant to UOM_CHOICES:
# two spellings of the same unit in the dropdown would let two people record the
# same thing differently, and then "hours" would never total correctly.
# Keys are compared uppercased.
UOM_ALIASES = {
    "HRS": "Hour", "HR": "Hour", "HOURS": "Hour",
    "NOS.": "Nos", "NO": "Nos", "PCS": "Nos", "PIECE": "Nos",
    "MTR": "Metre", "MTS": "Metre", "M": "Metre",
    "LTR": "Litre", "LTRS": "Litre",
    "TONNE": "Ton", "TONNES": "Ton",
    "SQ FT": "Sqft", "SQFT": "Sqft", "SQ.FT": "Sqft",
    "CMT": "Cum", "CU M": "Cum",
    "BAGS": "Bag", "BOXES": "Box",
}


class UnitOfMeasure(models.Model):
    """
    THE UNIT MASTER — the vocabulary a material's `uom` has to come from.

    >>> ANCHOR: UOM-MASTER <<<
    ⚠ THIS WAS A HARDCODED LIST UNTIL SAAHIL POINTED OUT WHY IT COULD NOT BE.
      The original reasoning was that a fixed list cannot drift — two spellings
      of one unit let two people record the same thing differently, and then
      hours never total correctly. That holds right up until somebody else fills
      in a spreadsheet:

        "UOM master is needed as Uom is a drop down in excel, so how will that
         change in case there are future new uoms?"

      A missing unit is then not an inconvenience. Their row is rejected and
      they can do nothing about it but telephone you.

    ⚠ THE VALUE STORED ON A MATERIAL IS STILL TEXT, NOT A FOREIGN KEY.
      `Material.uom` remains the string "Bag". This table is what that string is
      CHECKED against, not what it points at. So nothing that prints changes —
      the purchase order still reads "500 Bag" — and no migration has to touch
      705 materials or the documents pointing at them.

      The same shape as a material code: the text is the identity, the table is
      the vocabulary.

    ⚠ THE ALIASES LIVE HERE TOO, and that is the part that replaces the
      protection the hardcoded list gave. HRS, HR and HOURS all mean Hour. If
      the table is editable and the aliases are not, the drift comes straight
      back the first time a spreadsheet says "Hrs".

    ⚠ A CODE LOCKS ONCE ANYTHING USES IT. Because the value is stored as text,
      renaming "Bag" to "Bags" would orphan every material carrying the old
      spelling — the same failure as renaming an activity. Deactivate, never
      rename; and a delete is blocked while anything references it.
    """
    code = models.CharField(
        max_length=20, unique=True,
        help_text='What is stored on the material and printed on a document — "Bag", "Cum".')
    name = models.CharField(
        max_length=60, blank=True,
        help_text="Spelt out, if the code is not obvious. Cum → cubic metre.")
    aliases = models.CharField(
        max_length=200, blank=True,
        help_text="Other spellings a spreadsheet might use, comma separated. "
                  "HRS, HR, HOURS all mean Hour.")
    # ⚠ Deactivate rather than delete. An inactive unit disappears from every
    #   dropdown while every material that already carries it still resolves.
    is_active = models.BooleanField(
        default=True, help_text="Off takes it out of every dropdown. Nothing already using it breaks.")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "code"]
        verbose_name = "unit of measure"
        verbose_name_plural = "units of measure"

    def __str__(self) -> str:
        return f"{self.code} — {self.name}" if self.name else self.code

    @property
    def in_use(self) -> int:
        """How many materials carry this unit. Nonzero means it cannot be renamed."""
        return Material.objects.filter(uom=self.code).count()

    def delete(self, *args, **kwargs):
        """
        ⚠ BLOCKED WHILE ANYTHING USES IT — the same delete rule as everywhere
          else: nothing references it, real delete; something does, refuse and
          offer Deactivate.

          It has to be enforced here rather than by the database, because
          `Material.uom` is TEXT and not a foreign key, so there is no
          on_delete=PROTECT to do it for us. Deleting "Bag" would leave ten
          materials carrying a unit that no longer exists in the vocabulary.
        """
        count = self.in_use
        if count:
            raise ProtectedError(
                f"{self.code} is used by {count} material{'' if count == 1 else 's'}. "
                f"Turn it off with Active instead — that takes it out of every dropdown "
                f"while everything already using it keeps working.", {self})
        return super().delete(*args, **kwargs)

    def clean(self):
        """
        ⚠ THE CODE LOCKS ONCE ANYTHING USES IT. Renaming "Bag" to "Bags" would
          orphan every material carrying the old spelling — the value is stored
          as text, so nothing follows the rename. Same failure as renaming an
          activity, same rule.

        ⚠ AND A NEW UNIT IS WARNED ABOUT IF IT RESEMBLES AN EXISTING ONE. This
          is what replaces the protection the hardcoded list used to give: it was
          safe from drift because nobody could add anything. Now they can, so
          typing "Bags" beside "Bag" has to be a deliberate act rather than an
          accident. It is a REFUSAL WITH A NAMED ALTERNATIVE, not a silent merge
          — the system never decides two units are the same.
        """
        super().clean()
        if self.pk:
            was = UnitOfMeasure.objects.filter(pk=self.pk).values_list("code", flat=True).first()
            if was and was != self.code and Material.objects.filter(uom=was).exists():
                raise ValidationError({"code": (
                    f"{was} is already on materials, so its code cannot change — nothing would "
                    f"follow the rename. Turn this one off and add a new unit instead.")})
        else:
            from .imports import similarity
            for other in UnitOfMeasure.objects.all():
                if similarity(self.code, other.code) >= 0.85:
                    raise ValidationError({"code": (
                        f"“{self.code}” is very close to “{other.code}”, which already exists. "
                        f"If they are genuinely the same unit, use {other.code} and add "
                        f"“{self.code}” to its list of other spellings instead.")})


def active_uom_choices():
    """
    The units a dropdown should offer, newest state every time it is called.

    ⚠ NOT `Material.uom.choices`. Putting these on the field would mean a
      migration every time somebody adds a unit, which is precisely the friction
      this table exists to remove. The field is a plain CharField; validation
      happens where data enters — the material form, and the spreadsheet import.
    """
    return [(u.code, f"{u.code} — {u.name}" if u.name else u.code)
            for u in UnitOfMeasure.objects.filter(is_active=True)]


def resolve_uom(raw):
    """
    Turn a spreadsheet's unit text into a unit we know, or return None if it is
    not recognised. Never guesses — an unknown unit is reported, not assumed.

    ⚠ READS THE TABLE, WITH THE HARDCODED LISTS AS A FALLBACK. The fallback is
      not decoration: migrations run before the table is populated, and the test
      suite builds a database from nothing. Without it, importing during a
      migration would silently reject every unit.

    ⚠ AN INACTIVE UNIT STILL RESOLVES. Deactivating one takes it out of the
      dropdowns; it must not start rejecting the 618 materials that already
      carry it. Inactive means "do not offer this again", never "this is wrong".
    """
    text = (raw or "").strip()
    if not text:
        return None

    try:
        units = list(UnitOfMeasure.objects.all())
    except Exception:                      # no table yet — mid-migration
        units = []

    if units:
        by_code = {u.code.upper(): u.code for u in units}
        if text.upper() in by_code:
            return by_code[text.upper()]
        for unit in units:
            spellings = {a.strip().upper() for a in unit.aliases.split(",") if a.strip()}
            if text.upper() in spellings:
                return unit.code

    if text in {choice for choice, _ in UOM_CHOICES}:
        return text
    return UOM_ALIASES.get(text.upper())

digits_only = RegexValidator(r"^\d*$", "Digits only — no spaces, plus signs or dashes.")
gstin_format = RegexValidator(
    r"^$|^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}$",
    "A GSTIN is 15 characters, e.g. 24ABCDE1234F1Z5.",
)


# Three capital letters. Used as the first segment of every material code,
# e.g. the PLM in PLM-PL3-014.
activity_abbreviation = RegexValidator(
    r"^[A-Z]{3}$",
    "Exactly three capital letters, e.g. RCC. It becomes the first part of "
    "every material code under this activity.",
)


class Activity(models.Model):
    """
    THE ACTIVITY MASTER — every trade the company has ever used.

    Renamed from TradeDefault on 5 Aug 2026. It was only ever a list of default
    rates; it is really the master list that projects, materials and the BOM all
    point at.

    ⚠ MOVED HERE FROM THE `projects` APP IN SLICE 8, ON SAAHIL'S CALL.
      It had lived in `projects` so that the dependency ran one way — "projects
      knows about masters, masters knows nothing about projects". That held only
      while nothing in masters needed an activity. Once a material names its
      trade and a vendor names the trades they serve, masters needs it, and the
      honest fix is to admit what this row has always been:

        "It's basically the activities that belong in the BOQ are to come from
         a particular master data and the masters material master … is supposed
         to have a reference to an activity."

      It is master data. It sits on the Master data page beside Material groups
      and Vendor groups. It now lives with them, and the dependency still runs
      one way — the other way.

    ⚠ THE TABLE IS STILL CALLED `projects_activity` AND IS NOT RENAMED.
      Moving a model between apps and renaming its table are two separate risks,
      and only one of them buys anything. Nothing reads a table name; renaming it
      would rewrite a table that every purchase order, BOM line and estimate
      points at, to make a word tidier in a database nobody opens. The Meta
      below pins it, so the move is pure bookkeeping in Django's own state.

    Two lists that are easy to confuse and must stay separate:
      1. THIS — every activity the company has. Grows slowly, on purpose.
      2. EstimateLine — the activities selected onto ONE project, with that
         project's rates. Removing one there deselects it; this row survives.

    Saahil's rule: a parameter must exist here before any project can use it,
    "the same way a user creates a material group in SAP".
    """

    # >>> ANCHOR: CODE-GEN <<<
    # This abbreviation is the first segment of every material code created
    # under this activity. Changing it does NOT rewrite existing codes — codes
    # are assigned once and never regenerated, so an old code may name an
    # abbreviation that has since changed. That is deliberate: a code printed on
    # a purchase order must never stop resolving. Nothing in the system parses a
    # code to work out its activity; that is what the FK is for.
    abbreviation = models.CharField(
        max_length=3, unique=True, validators=[activity_abbreviation],
        help_text="Three capital letters, typed by you. Must be unique — the system checks. "
                  "Auto-deriving from the name collides (Fabrication vs Fire Fighting).",
    )
    name = models.CharField(max_length=120, unique=True)
    rate = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)],
                               help_text="Rupees per sqft of built-up area. EX-GST.")
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=18)
    basis = models.CharField(max_length=300, blank=True,
                             help_text="Specification assumption shown beside the rate")
    sort_order = models.PositiveIntegerField(default=0, help_text="Order of work on site")

    # Deactivate, never delete, once anything references it. See the delete rule
    # in PROJECT-CONTEXT.md: delete means "this was a mistake", deactivate means
    # "we have stopped using this". An inactive activity disappears from every
    # picker but every historical record still resolves.
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]
        # ⚠ THE LABEL CHANGED, THE MODEL DID NOT. Saahil asked for the word on
        #   screen to be "construction activity" — his people say trade or
        #   construction activity, never "activity" on its own. The class, the
        #   table and every relation keep their names; only what a reader sees
        #   moves, which is why this is a verbose_name and not a rename.
        verbose_name = "construction activity"
        verbose_name_plural = "construction activities"
        # ⚠ PINNED. See the note above — the model moved apps, the table did not.
        db_table = "projects_activity"

    def __str__(self) -> str:
        return f"{self.abbreviation} — {self.name}"

    @property
    def estimates_using_the_name(self) -> int:
        """
        How many estimate lines copied this activity's name. Nonzero means the
        name is load-bearing and cannot change.
        """
        from projects.models import EstimateLine
        return EstimateLine.objects.filter(name=self.name).count()

    def clean(self):
        """
        >>> ANCHOR: ACTIVITY-RENAME-BLOCKED <<<
        ⚠⚠ THE NAME CANNOT CHANGE ONCE AN ESTIMATE HAS COPIED IT.

          An estimate line COPIES the activity's name when it is created, and
          the reserve is found again later by matching that name back:

              estimate.lines.filter(name=activity.name)

          So renaming "RCC" silently drops the reserve to ZERO on every project
          quoting RCC. No error, no warning, on live jobs — the BOM simply
          starts reporting that a trade with a budget has no budget.

        ⚠ THIS WAS A CONVENTION, NOT A RULE, UNTIL NOW. The Company rates screen
          did not show the name field and that was the entire protection —
          Django Admin renamed activities happily. Saahil believed it was
          already blocked: "Renaming is not possible… If an activity is created,
          it stays. And then if they don't want to use it, they can simply
          deactivate it." The belief and the code had been out of step the whole
          time; nobody found out because nobody tried.

        ⚠ SAME SHAPE AS UnitOfMeasure.clean(), and for the same reason: a value
          copied as TEXT has nothing that follows a rename. It is a REFUSAL WITH
          A NAMED ALTERNATIVE — deactivate and add a new one.

        ⚠ AND IT LIVES IN THE MODEL, not in a view. Admin has to obey it too, or
          the one route that could do the damage is the one route left unguarded.

        ⚠ THE REAL FIX IS TO LINK THE RESERVE BY ID. That is a schema change and
          is on the go-live list. Until then this guard is what stands between a
          rename and a silent zero.
        """
        super().clean()
        if not self.pk:
            return
        was = (Activity.objects.filter(pk=self.pk)
               .values_list("name", flat=True).first())
        if was is None or was == self.name:
            return
        # ⚠ COUNTED AGAINST THE OLD NAME, not the new one. The lines carrying the
        #   old spelling are exactly the ones that would be orphaned.
        from projects.models import EstimateLine
        used = EstimateLine.objects.filter(name=was).count()
        if used:
            raise ValidationError({"name": (
                f"“{was}” is on {used} estimate line{'' if used == 1 else 's'}, so its name "
                f"cannot change — the reserve is matched by name and nothing would follow the "
                f"rename. Turn this one off with Active and add a new construction activity "
                f"instead.")})


class MaterialGroup(models.Model):
    """
    How materials are grouped — the second segment of every material code.

    ⚠⚠ `is_active` WAS MISSING AND THE SCREEN DREW IT ANYWAY. The three
       code-and-name masters share one template, which prints an Active column
       for all of them; this model had no such field, so all 25 rows rendered
       unchecked, looked deactivated, and ticking one did nothing. The save path
       guarded with `hasattr` so nothing was ever corrupted — it was a control
       that could not fail because it could not act. Saahil found it on screen.

    ⚠ THE FIX IS THE FIELD, NOT REMOVING THE COLUMN, because the rule the whole
      app follows is that nothing is deleted and Active is the route out. A group
      nobody uses any more needs some way to be retired, and its sisters
      (VendorGroup, UnitOfMeasure) both have one.
    """
    code = models.CharField(max_length=4, unique=True, help_text="e.g. CEM")
    name = models.CharField(max_length=60, help_text="e.g. Cement & Binders")
    is_stock_item = models.BooleanField(
        default=True,
        help_text="Off for services like Site Expense and Transport — orderable, but never held in stock.",
    )
    # ⚠ "DO NOT OFFER THIS AGAIN", NEVER "THIS IS WRONG". Deactivating stops the
    #   group being CHOSEN for a new material. It does not touch the materials
    #   already in it and it cannot touch their codes — the group code is the
    #   middle segment of every one of them and codes are assigned once
    #   (ANCHOR: CODE-GEN). Same meaning the unit master's flag already carries.
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class Material(models.Model):
    # >>> ANCHOR: CODE-GEN <<<
    # ACTIVITY-GROUP-SERIAL, e.g. PLM-PL3-014. The first segment is the
    # abbreviation of the material's HOME activity (see projects.Activity), the
    # second is its group, the third a serial that restarts within each
    # activity+group pair.
    #
    # A code is assigned ONCE and NEVER regenerated. Reclassify a material and
    # it keeps its original code, so an old code may name a group it no longer
    # belongs to. That is deliberate — a code printed on a purchase order must
    # never stop resolving. NOTHING PARSES A CODE to work out group or activity;
    # the foreign keys are for that.
    code = models.CharField(max_length=20, unique=True,
                            help_text="ACTIVITY-GROUP-SERIAL, e.g. PLM-PL3-014. Generated, never typed.")
    name = models.CharField(max_length=200)
    group = models.ForeignKey(MaterialGroup, on_delete=models.PROTECT, related_name="materials")
    subgroup = models.CharField(max_length=6, default="GEN",
                                help_text="Carried over from the old code scheme. Not part of the new code.")
    specification = models.CharField(max_length=300, blank=True)
    # ⚠ NO `choices`, DELIBERATELY. The permitted values live in UnitOfMeasure,
    #   and putting them on the field would mean a migration every time somebody
    #   added a unit — the exact friction that table exists to remove. Validation
    #   happens where data enters: the material form and the spreadsheet import.
    uom = models.CharField(max_length=20)

    # >>> ANCHOR: MATERIAL-ACTIVITY <<<
    # WHICH TRADE THIS MATERIAL IS BOUGHT FOR. Two columns, not a link table.
    #
    # ⚠ THESE REPLACED THE `MaterialActivity` TABLE. Saahil's instruction:
    #   "Material is to be linked to activity in the same material master screen,
    #    not as a separate tile" — and, on why it belongs on the record itself,
    #   "All of these info will be used to do analytics, so it has to be present
    #    in the final tables i.e. Material master and Vendor Master."
    #
    # ⚠ THE RULE: A HOME ACTIVITY IS REQUIRED, A SECOND IS OPTIONAL, THERE IS NO
    #   THIRD. His words: "material may have the second activity as a blank, so
    #   enforce rule for the first activity cell, not the second, it should just
    #   use the second cell for search in case the user wishes it to belong in
    #   more than one." Two columns express that with nothing to enforce at all —
    #   a link table would have needed a count check to say the same thing.
    #
    # ⚠ THE MIGRATION WAS LOSSLESS. Every one of the 705 materials had exactly
    #   one MaterialActivity row when this changed, so no second activity existed
    #   to drop. Measured before writing it, not assumed.
    #
    # ⚠ WHY A STRING REFERENCE AND NOT AN IMPORT. MaterialActivity lived in the
    #   projects app on purpose, so that "projects knows about masters, masters
    #   knows nothing about projects". Naming the model as a string keeps that
    #   true of the Python — there is still no import of projects here. Only the
    #   migration graph gains an edge, which Django resolves without complaint.
    #   If this ever becomes awkward, the clean fix is moving Activity into
    #   masters, where a trade master arguably belongs anyway.
    #
    # ⚠ AND NOTHING PARSES THE CODE TO FIND THIS. The code carries the home
    #   activity's abbreviation from the day it was created and is never
    #   regenerated, so a reclassified material's code names where it was born.
    #   This column names where it is used. They are allowed to disagree.
    # ⚠ NOT NULLABLE. The rule is enforced by the column, not by a habit — the
    #   migration adds it nullable, fills it from MaterialActivity, then tightens
    #   it, so no code path anywhere can leave a material without a trade.
    home_activity = models.ForeignKey(
        Activity, on_delete=models.PROTECT, related_name="home_materials",
        help_text="The construction activity this material belongs to. Required.",
    )
    also_used_in = models.ForeignKey(
        Activity, on_delete=models.PROTECT, related_name="secondary_materials",
        null=True, blank=True,
        help_text="A second trade that also buys it. Optional — leave blank for almost everything.",
    )

    # >>> ANCHOR: BOM-MATERIAL-FILTER <<<
    # Consumables used across every trade — wall plugs, fevicol, hacksaw blades.
    # A common material appears in EVERY activity's dropdown, whatever its home.
    #
    # A flag rather than a link row per activity, deliberately: with link rows,
    # adding a 19th activity later would silently leave all of these out of it.
    # A flag stays true for activities that do not exist yet.
    is_common = models.BooleanField(
        default=False,
        help_text="Used across every trade. Appears in every activity's material list.",
    )

    estimation_rate = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        validators=[MinValueValidator(0)],
        # ⚠ IT DOES NOT DRIVE THE BOQ, WHICH THIS SAID FOR MONTHS. The BOQ is
        #   built from Activity.rate — rupees per sqft of built-up area. This is
        #   the BOM's planning rate when a line has no project-specific one.
        help_text="The BOM's planning value. Not a vendor price.",
    )
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=18)
    hsn_code = models.CharField(max_length=10, blank=True, help_text="Filled on first use. Required on a GST invoice.")

    reorder_level = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    current_stock = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    search_aliases = models.CharField(
        max_length=300, blank=True,
        help_text='Site vocabulary — "saria" finds TMT bar, "chips" finds aggregate.',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        indexes = [models.Index(fields=["name"]), models.Index(fields=["group", "subgroup"])]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

    def clean(self):
        """
        ⚠ THE SECOND ACTIVITY MAY NOT REPEAT THE FIRST.

        Saying a material is used in RCC and also in RCC is not a second trade,
        it is a typo — and it would make the BOM search match the same material
        twice for one activity. The column being nullable is what allows blank;
        this is the only thing left to check.
        """
        super().clean()
        if self.also_used_in_id and self.also_used_in_id == self.home_activity_id:
            raise ValidationError({
                "also_used_in": "That is already the home activity. Leave it blank unless the "
                                "material is genuinely bought under a second trade.",
            })


class DocumentType(models.TextChoices):
    """
    Purchase Order or Work Order.

    >>> ANCHOR: DOCUMENT-TYPE <<<
    ONE ENGINE, TWO DOCUMENTS. The model, the lines, every calculation, the
    lifecycle and the PDF are identical. Only four things differ, and only two
    of those are more than wording:

      * the NumberSeries key      -> PO-000001 vs WO-000001, two counters   (real)
      * which terms block is used -> CompanyProfile.po_terms / .wo_terms    (real)
      * the title and party label -> "TO — VENDOR" vs "TO — CONTRACTOR"     (display)
      * Delivered vs Completed    -> material arrives; labour is finished   (display)

    It lives here rather than on PurchaseOrder because the VENDOR decides it —
    see Vendor.default_document_type below — and masters cannot import projects.
    """
    PO = "PO", "Purchase Order"
    WO = "WO", "Work Order"


class CompanyProfile(models.Model):
    """
    Us. One row, ever.

    WHAT THIS FILE IS FOR
        Every document we issue prints our own name, address and GSTIN at the
        top. Before this existed there was nowhere to put them, and the only
        alternative was hard-coding the client's details into a template — the
        kind of thing that survives into production and is found by a customer.

    ⚠ OUR GSTIN IS NOT DECORATION. Its first two digits are half of the
      CGST+SGST vs IGST decision; the vendor's GSTIN is the other half.

    ⚠ ONE ROW, ENFORCED. save() pins the primary key to 1. A second row would
      silently change which letterhead prints, and nobody would know which was
      being used until a vendor asked.
    """
    name = models.CharField(max_length=200, default="Elegance Skyz Pvt. Ltd.")
    address = models.TextField(blank=True)
    gst_number = models.CharField(max_length=15, blank=True, validators=[gstin_format],
                                  help_text="Ours. The first two digits decide CGST+SGST vs IGST.")
    state = models.CharField(max_length=60, blank=True, help_text="Derived from our GSTIN.")
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=15, blank=True, validators=[digits_only])
    # ⚠ FileField, NOT ImageField. ImageField requires Pillow, and CI installs
    #   only Django, python-dotenv and openpyxl — so `manage.py check` would
    #   pass on a laptop and fail on every pull request. We do not need image
    #   validation for a letterhead logo.
    logo = models.FileField(upload_to="company/", blank=True, null=True)

    # >>> ANCHOR: DOC-TERMS <<<
    # The standard terms printed on every document. Two blocks, because a
    # materials order talks about rejection, e-way bills and delivery, while a
    # contractor's work order talks about labour, safety and stage completion.
    # One block loose enough to cover both would protect us in neither.
    #
    # ⚠ COPIED onto each document when its draft is created — never read live.
    #   Editing these next year must not rewrite the terms on an order already
    #   sent to a vendor. That is the copy-don't-link rule; the live-linked
    #   activity reserve remains the only documented exception in the system.
    po_terms = models.TextField(
        blank=True,
        default=("1. This order number must appear on your invoice, delivery challan and e-way bill.\n"
                 "2. Material to be supplied as per the description, specification and quantity above. "
                 "Goods rejected at site are to be lifted by the supplier at their own cost.\n"
                 "3. Payment as per the terms above, against a valid GST invoice and signed delivery challan."),
        help_text="Printed on purchase orders. Copied onto each order when it is created.",
    )
    wo_terms = models.TextField(
        blank=True,
        default=("1. This order number must appear on your invoice and every running bill.\n"
                 "2. Work to be carried out as per the scope above, including labour, tools and site "
                 "cleaning unless stated otherwise.\n"
                 "3. Payment against certified work, as per the terms above."),
        help_text="Printed on work orders. Copied onto each order when it is created.",
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "company profile"
        verbose_name_plural = "company profile"

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        """Always row 1. There is only ever one company."""
        self.pk = 1
        if self.gst_number:
            self.state = STATE_BY_CODE.get(self.gst_number[:2], "")
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        """The company, creating the row with its defaults on first use."""
        profile, _ = cls.objects.get_or_create(pk=1)
        return profile


class VendorGroup(models.Model):
    """
    WHAT A VENDOR IS, in the words somebody would search with.

    >>> ANCHOR: VENDOR-GROUP <<<
    Mirrors MaterialGroup deliberately: a short code, a name, one per record.
    Seeded from the 37 free-text categories that used to live on a link table —
    Cement, Flooring Material, Fabricator, Structure Engineer, Torrent Power.

    ⚠ THIS IS NOT AN ACTIVITY AND MUST NEVER BE MERGED INTO ONE. That was
      proposed, agreed, and then correctly reversed by Saahil once we looked at
      all 37 together: "lets use vendor category as an identifier to search
      vendor … lets not mix vendor category and link them to Vendor Activities."

      The list is a mix of material types (Cement, Red Bricks), services
      (Fabricator, Piling), consultants (MEPF Consultant) and a utility (Torrent
      Power). It answers WHAT THIS VENDOR IS. `Vendor.activity_1/2` answers
      WHICH TRADE THEY SERVE, and that is the one the BOM filters on. Two
      questions, two fields, and collapsing them loses the ability to ask either.

    ⚠ ONE GROUP PER VENDOR. Nine vendors carried more than one category. Four of
      those resolved on their own — their second value was never a group, it was
      an activity, so Mukesh Dayaji became group "Sand / Aggregate" with activity
      Earthwork. The remaining five are builders' merchants who genuinely sell
      several things, and Saahil chose which group each keeps. Named on a review
      list first; nothing was dropped silently.
    """
    # ⚠ NO CODE FIELD, UNLIKE MaterialGroup, AND THAT IS DELIBERATE.
    #   A material group has a code because it is part of the material's code —
    #   RCC-CEM-001. A vendor's code is VEN-020 and embeds nothing, so a vendor
    #   group code would be a value nothing reads, nobody types and everyone has
    #   to invent. The name is the key, on the screen and in the spreadsheet.
    name = models.CharField(max_length=60, unique=True,
                            help_text="e.g. General Construction Material")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Vendor(models.Model):
    code = models.CharField(max_length=12, unique=True, help_text="e.g. VEN-001")
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=120, blank=True)

    phone = models.CharField(max_length=15, unique=True, validators=[digits_only],
                             help_text="Digits only. This is the vendor's identity — never dedupe by name.")
    whatsapp_number = models.CharField(max_length=15, blank=True, validators=[digits_only],
                                       help_text="91 + 10 digits. Blank for landlines and 1800 numbers.")
    secondary_contact = models.CharField(max_length=120, blank=True)
    secondary_phone = models.CharField(max_length=15, blank=True, validators=[digits_only])
    email = models.EmailField(blank=True)

    gst_number = models.CharField(max_length=15, blank=True, validators=[gstin_format],
                                  help_text="Captured on the first purchase order. Editable only here.")

    # >>> ANCHOR: GSTIN-CAPTURE <<<
    # A purchase order normally cannot be approved without the vendor's GSTIN.
    # That is right for a registered supplier and wrong for the hardware shop
    # down the road, who has no GST number and never will.
    #
    # Tick this and approval stops asking, and their purchase-order lines are
    # raised at 0% GST — an unregistered supplier cannot charge it. The order is
    # still a real, numbered, permanent record, which is the point: Saahil wants
    # cash and street purchases captured for budgeting and analytics rather than
    # left off the system because they do not fit the paperwork.
    #
    # A property of the VENDOR, not of each order, so it is decided once and
    # every future order to them behaves correctly without anyone remembering.
    is_unregistered = models.BooleanField(
        default=False,
        help_text="Tick for a local or street supplier with no GST registration. Their purchase "
                  "orders need no GSTIN and are raised at 0% GST.",
    )
    state = models.CharField(max_length=60, blank=True, help_text="Derived from the first 2 digits of the GSTIN.")
    address = models.TextField(blank=True)
    payment_terms = models.CharField(max_length=60, blank=True)

    # >>> ANCHOR: DOCUMENT-TYPE <<<
    # WHO WE ARE ORDERING FROM DECIDES WHAT DOCUMENT COMES OUT.
    #
    # A cement supplier gets a purchase order; a labour contractor gets a work
    # order. Post POs already groups the BOM by vendor — one document per vendor
    # — so the type falls out per group with nothing extra for anyone to choose.
    #
    # ⚠ NOT decided by the materials on the lines. Transport is a service
    #   material, and a transport line sitting on a cement order is plainly part
    #   of that purchase order, not a separate work order. Inferring from line
    #   content also means the type would change as lines were edited, and a
    #   document's number series cannot depend on what somebody typed a minute
    #   ago.
    #
    # A DEFAULT, NOT A RULE: a fabricator may supply grills and also install
    # them. The Post POs preview shows the type per vendor and lets it be
    # switched before anything is created. Pre-fill helps, never blocks.
    # >>> ANCHOR: VENDOR-CLASSIFICATION <<<
    # Two fields answering two different questions, and they are not
    # interchangeable. See VendorGroup for why merging them was reversed.
    #
    #   group        WHAT THEY ARE   — how you find them when searching
    #   activity_1/2 WHICH TRADE     — what the BOM filters its dropdown on
    #
    # ⚠ BOTH OPTIONAL. Saahil's call: a vendor can be entered with a phone number
    #   and nothing else, which is how they actually arrive. A required field
    #   here would be filled in with whatever was nearest.
    #
    # ⚠ TWO ACTIVITIES, MIRRORING MATERIALS. A builders' merchant genuinely
    #   supplies RCC and masonry. Two is where the same rule landed on the
    #   material master, and consistency between the two screens is something
    #   Saahil notices.
    group = models.ForeignKey(
        VendorGroup, on_delete=models.PROTECT, related_name="vendors",
        null=True, blank=True,
        help_text="What this vendor is — used to search the vendor list.",
    )
    activity_1 = models.ForeignKey(
        Activity, on_delete=models.PROTECT, related_name="primary_vendors",
        null=True, blank=True,
        help_text="Which trade they serve. Used to offer the right vendors on a BOM line.",
    )
    activity_2 = models.ForeignKey(
        Activity, on_delete=models.PROTECT, related_name="secondary_vendors",
        null=True, blank=True,
        help_text="A second trade, if they serve one.",
    )

    # ⚠ TWO VALUES, AND PO STAYS THE DEFAULT. A third "both" option was proposed
    #   and Saahil declined it: "no, it is rare to have both but, keep PO as
    #   default". A vendor who does both is handled per document — this field
    #   only decides which type a new draft starts as, and the preview can switch
    #   it before anything is written.
    default_document_type = models.CharField(
        max_length=2, choices=DocumentType.choices, default=DocumentType.PO,
        help_text="Work Order for labour contractors, Purchase Order for suppliers. "
                  "Can be switched per order on the preview.",
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

    def save(self, *args, **kwargs):
        """
        Tidy the phone number, and fill in WhatsApp only when it is blank.

        WHY "ONLY WHEN BLANK" MATTERS
            This used to derive the WhatsApp number on EVERY save, which quietly
            threw away anything typed by hand. That is wrong for the vendors who
            need it most: Schindler and TKE publish 1800 numbers, which WhatsApp
            cannot reach, so somebody has to enter a mobile manually — and it
            would have been wiped on the next save.

            So: leave it blank and it fills itself; type one and yours is kept.
            To go back to the automatic value, clear the field and save again.
        """
        digits = "".join(ch for ch in (self.phone or "") if ch.isdigit())
        self.phone = digits

        if not (self.whatsapp_number or "").strip():
            # A 10-digit Indian mobile starts 6, 7, 8 or 9. Anything else — a
            # landline or an 1800 number — is left blank rather than turned into
            # a number that would fail silently when a PO is sent.
            self.whatsapp_number = "91" + digits if len(digits) == 10 and digits[0] in "6789" else ""
        else:
            self.whatsapp_number = "".join(ch for ch in self.whatsapp_number if ch.isdigit())

        if self.gst_number and len(self.gst_number) == 15 and not self.state:
            self.state = STATE_BY_CODE.get(self.gst_number[:2], "")

        super().save(*args, **kwargs)


class VendorCategory(models.Model):
    """A vendor often supplies several trades — Sambhav Hardware covers four."""
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="categories")
    category = models.CharField(max_length=60)

    class Meta:
        unique_together = [("vendor", "category")]
        verbose_name_plural = "vendor categories"

    def __str__(self) -> str:
        return f"{self.vendor.code} · {self.category}"


class VendorRate(models.Model):
    """
    The link table between vendors and materials. A helper, never a gate —
    if a combination is missing the buyer simply types the rate on the PO,
    and it is written back here on approval.

    >>> ANCHOR: VENDOR-RATE-CAPTURE <<<
    ⚠⚠ THE WRITE-BACK IN THAT SENTENCE DID NOT EXIST UNTIL NOW. The docstring
       described the intent from the beginning and nothing implemented it, so
       the table stayed empty on a live system with approved orders in it and
       the screen said "they appear as purchase orders are raised" — a promise
       the code never kept. Saahil found it on screen: "There were a few
       approved POs, yet I saw this as empty."

    ⚠ ONE ROW PER VENDOR AND MATERIAL, REPLACED ON EVERY APPROVAL. His call,
      and he named the precedent: "we should do like SAP, if the vendor/material
      combination exist, we replace it." So this answers *what is the rate with
      this vendor today*, not *what has it been*. Nothing is lost by replacing —
      the full trail is on the purchase order lines, which is the honest source
      for any question about history.

    ⚠ `source_po_line` IS WHAT MAKES THE REPLACE LEGIBLE. Without it the row is
      a number with no provenance and no way to ask where it came from. With it
      the screen can say ₹340, PO-000031, 12 July — and when the next order
      lands, all three change together. SET_NULL rather than CASCADE: losing the
      order that proved a rate must not silently delete the rate itself.
    """
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="rates")
    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="vendor_rates")
    rate = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    lead_time_days = models.PositiveIntegerField(null=True, blank=True)
    is_preferred = models.BooleanField(default=False)
    last_updated = models.DateTimeField(auto_now=True)

    # ⚠ A STRING REFERENCE, DELIBERATELY. `projects` imports `masters`; importing
    #   back the other way at module level is the circular import that this app
    #   has avoided everywhere else.
    source_po_line = models.ForeignKey(
        "projects.PurchaseOrderLine", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="captured_rates",
        help_text="The approved order line this rate was taken from.")

    class Meta:
        unique_together = [("vendor", "material")]
        ordering = ["material", "rate"]

    def __str__(self) -> str:
        return f"{self.vendor.name} · {self.material.name} · ₹{self.rate}"


class PanelTranslation(models.Model):
    """
    One ⓘ step, in Gujarati, written by the people who speak it.

    >>> ANCHOR: INFO-PANELS <<<
    ⚠⚠ AN OVERLAY, NOT A COPY OF THE PANELS. The English lives in
       `projects/help_panels.py` and ships with the app; a row here exists only
       where somebody has written a translation. An install nobody has touched
       behaves exactly as it did before this table existed, and clearing a box
       falls back to no translation rather than to a blank panel.

       The alternative — every panel in the database, seeded once — was
       considered and rejected: the app's own instructions would stop following
       the app. Rename a button in a commit and the panel would still name the
       old one, with nothing anywhere to notice.

    ⚠⚠ GUJARATI ONLY. THE ENGLISH IS NOT EDITABLE HERE, and neither is the
       structure. Saahil: "Structure should never be editable in reality,
       especially by a user." Adding, deleting or reordering steps would let the
       panel drift from the screen it describes; rewording the English would let
       it drift from the tests that check its shape. Words in one language is
       the safe half of the idea.

    ⚠⚠ `source_english` IS WHAT MAKES THIS SAFE OVER TIME. A translation is
       written against a particular English instruction. When that instruction
       later changes, the Gujarati silently describes something that no longer
       exists — and nobody reading only Gujarati could ever find out. So the
       English it was written from is stored beside it, and the editing screen
       flags every row where the two have parted company. The same failure shape
       as the BOQ reserve matching on a name, caught by design rather than by
       somebody remembering.

    ⚠ KEYED BY THE STEP'S LABEL, not its position. Inserting a step in the
      middle would shift every index below it and quietly re-attach translations
      to the wrong instructions. Labels are unique within a panel, and a test
      says so.
    """

    panel_key = models.CharField(max_length=40)
    step_label = models.CharField(max_length=40)
    gujarati = models.TextField(blank=True)
    # The English this was written from. Blank on a row created before the
    # English was known, which cannot happen through the screen.
    source_english = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="panel_translations")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["panel_key", "step_label"],
                                    name="one_translation_per_step"),
        ]
        ordering = ["panel_key", "step_label"]

    def __str__(self):
        return f"{self.panel_key} · {self.step_label} (ગુ)"


STATE_BY_CODE = {
    "24": "Gujarat", "27": "Maharashtra", "07": "Delhi", "29": "Karnataka",
    "33": "Tamil Nadu", "08": "Rajasthan", "09": "Uttar Pradesh", "23": "Madhya Pradesh",
    "19": "West Bengal", "36": "Telangana", "37": "Andhra Pradesh", "32": "Kerala",
    "06": "Haryana", "03": "Punjab", "10": "Bihar", "21": "Odisha",
}
