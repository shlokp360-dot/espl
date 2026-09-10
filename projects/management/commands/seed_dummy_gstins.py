"""
Fill vendor GST numbers with obviously-fake ones so testing is not blocked.

    python manage.py seed_dummy_gstins --dry-run   count it, change nothing
    python manage.py seed_dummy_gstins             fill them
    python manage.py seed_dummy_gstins --remove    take every dummy away again

>>> ANCHOR: DUMMY-GSTINS <<<
WHY THIS EXISTS
    `po_service.approve()` hard-blocks when a vendor has no GST number, and 170
    of the 174 vendors have none. On a test database that means almost nothing
    can be approved, so the whole downstream half of the app — delivery,
    payment, the printed order, vendor rates, spend analytics — cannot be walked
    through at all. Saahil's call, 16 Aug: real GSTINs get collected over the
    project's life, so put dummies in for now.

⚠⚠ THE HARD BLOCK IS NOT WEAKENED. Not one line of `approve()` changes. This
   fills DATA that satisfies the rule. The rule is correct and must stay: a
   purchase order legally cannot be issued without the vendor's GSTIN.

⚠⚠ EVERY NUMBER THIS WRITES SAYS `ZZDMY` IN THE PAN BLOCK, ON PURPOSE.
   A dummy that looks real is the dangerous kind — it survives to production,
   prints on an order actually sent to a vendor, and lands in a filed return.
   `24ZZDMY0007Z1Z5` passes `gstin_format` and is unmistakable at a glance, in
   an export, and on the printed order. It is also what `--remove` matches on,
   so removal can never take away a real number somebody typed.

⚠ MIXED STATE CODES, DELIBERATELY. Most vendors are Gujarat (`24`), which is
  true of the real ones in Ahmedabad, but a handful are out of state so
  `_is_interstate()` actually fires. All-Gujarat would leave the IGST branch
  untested — and that branch decides whether a document prints CGST + SGST or
  IGST, which is a real tax error if it is wrong.

⚠⚠ OUR OWN GSTIN IS SET TOO, AND IT IS NOT OPTIONAL. `_is_interstate()` returns
   False whenever the company GSTIN is blank, so without it EVERY order prints
   CGST + SGST no matter where the vendor is. Filling vendor numbers alone would
   have produced a database where approval works and the tax split is silently
   always-local — worse than being blocked, because it looks right.

⚠⚠ A DELIBERATE HOLDBACK IS LEFT WITH NO GSTIN. The vendor master header counts
   "N without a GSTIN" and that number ties straight to the go-live gap. Filling
   all 174 would make it read 0 and hide the thing it exists to show. So a set
   of vendors is left blank on purpose — and only vendors with NO purchase
   orders, so the holdback can never be what blocks an approval.

⚠ NEVER OVERWRITES A NUMBER SOMEBODY TYPED. Blanks are filled; anything already
  there is left exactly as it is. The one exception is the four early dummies
  built from the help text's own example (`ABCDE1234F1Z5`) — those are
  indistinguishable from real ones, which is the problem, so they are normalised
  onto the `ZZDMY` pattern. `--normalise-legacy` off turns that off.

⚠ REFUSES TO RUN WHEN DEBUG IS FALSE. The one guard that matters. A command that
  writes fake tax numbers must not be runnable against production by somebody
  working down a runbook.

⚠⚠ DOES NOT TOUCH `VENDOR_MASTER.xlsx`. That workbook is what seeds production
   (see G1 — the screen's export cannot). It must stay clean of dummies, so this
   command writes to the database and nowhere else.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from masters.models import CompanyProfile, Vendor, gstin_format
from projects.bom_models import PurchaseOrder

# The PAN block every dummy carries. Five letters, so it fits `[A-Z]{5}`, and it
# reuses the ZZ prefix already used for walkthrough rows everywhere else.
DUMMY_PAN = "ZZDMY"

# `24` is Gujarat and is ours, so these are the CGST + SGST cases. The others
# exercise IGST. Roughly one vendor in six is out of state, which is enough to
# see the branch without making the data absurd.
HOME_STATE = "24"
AWAY_STATES = ["27", "07", "29", "08", "33"]
AWAY_EVERY = 6

# Ours. Serial 9999 keeps it clear of the vendor range and out of any collision.
COMPANY_GSTIN = f"{HOME_STATE}{DUMMY_PAN}9999Z1Z5"

# How many vendors are left deliberately blank so the header count stays useful.
HOLDBACK = 12

# The four typed by hand at approval, from the help text's own example. Real in
# shape, fake in fact, and impossible to tell apart from a genuine one.
LEGACY_DUMMY_PAN = "ABCDE"


def dummy_for(serial):
    """
    A valid GSTIN that could not possibly be mistaken for a real one.

    Format is `^\\d{2}[A-Z]{5}\\d{4}[A-Z]{1}[A-Z\\d]{1}[Z]{1}[A-Z\\d]{1}$` —
    2 digits, 5 letters, 4 digits, a letter, an alphanumeric, a literal Z, an
    alphanumeric. `24ZZDMY0007Z1Z5` splits as 24 · ZZDMY · 0007 · Z · 1 · Z · 5.

    ⚠ The serial lives in the 4-digit block, so it holds 1..9999 — far more than
      the 174 vendors — and every vendor gets a DISTINCT number. One shared GSTIN
      across the whole master would be indistinguishable in analytics and in any
      report grouped by tax registration.
    """
    state = AWAY_STATES[(serial // AWAY_EVERY) % len(AWAY_STATES)] \
        if serial % AWAY_EVERY == 0 else HOME_STATE
    return f"{state}{DUMMY_PAN}{serial:04d}Z1Z5"


def is_dummy(gstin):
    """A number this command wrote. `--remove` clears these and nothing else."""
    return bool(gstin) and len(gstin) == 15 and gstin[2:7] == DUMMY_PAN


def is_legacy_dummy(gstin):
    """One of the four typed from the help text's example."""
    return bool(gstin) and len(gstin) == 15 and gstin[2:7] == LEGACY_DUMMY_PAN


class Command(BaseCommand):
    help = ("Fill blank vendor GST numbers with obviously-fake ones so purchase "
            "orders can be approved on a test database. Never runs when DEBUG is False.")

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would change and write nothing.")
        parser.add_argument("--remove", action="store_true",
                            help="Clear every dummy GSTIN this command wrote, and ours.")
        parser.add_argument("--holdback", type=int, default=HOLDBACK,
                            help=f"How many vendors to leave with no GSTIN on purpose "
                                 f"(default {HOLDBACK}). Only ever vendors with no orders.")
        parser.add_argument("--no-normalise-legacy", action="store_true",
                            help="Leave the four ABCDE1234F1Z5 dummies exactly as they are.")

    # ------------------------------------------------------------------ guard
    def _refuse_on_production(self):
        """
        ⚠ THE ONE GUARD THAT MATTERS. Everything else here is tidiness; this is
          the line between a convenience and a filed return with a fake GSTIN on
          it. DEBUG is False in production by definition — see `.env.example`.
        """
        if not settings.DEBUG:
            raise CommandError(
                "Refusing to run: DEBUG is False, so this looks like a production "
                "database. This command writes FAKE GST numbers and must never touch "
                "real vendor records. If this really is a test database, set "
                "DJANGO_DEBUG=True and run it again.")

    # ----------------------------------------------------------------- handle
    def handle(self, *args, **options):
        self._refuse_on_production()
        if options["remove"]:
            return self.remove(options["dry_run"])
        return self.fill(options)

    # ------------------------------------------------------------------- fill
    def fill(self, options):
        dry = options["dry_run"]

        # ⚠ Vendors that already have a purchase order can NEVER be held back —
        #   holding one back would be exactly the block this command exists to
        #   clear. Read the set once and exclude it from the holdback pool.
        with_orders = set(PurchaseOrder.objects.values_list("vendor_id", flat=True))

        vendors = list(Vendor.objects.order_by("code"))
        legacy = [] if options["no_normalise_legacy"] else \
            [v for v in vendors if is_legacy_dummy(v.gst_number)]

        # ⚠⚠ AN UNREGISTERED VENDOR IS NEVER TOUCHED AT ALL — not filled, and not
        #   counted as held back either. The tick means "has no GST registration
        #   and never will", so writing a number contradicts the flag and would
        #   raise their lines from 0% to the material rate. It is also already
        #   permanently blank, so letting it occupy a holdback slot would make
        #   the holdback number a lie: ask for 5 and 4 would actually be held.
        fillable = [v for v in vendors if not v.is_unregistered]

        # ⚠⚠ THE HOLDBACK IS CHOSEN OVER A STABLE POPULATION, NOT OVER "WHATEVER
        #   IS BLANK RIGHT NOW". Picking from the current blanks meant the set
        #   moved between runs — remove, refill, and a different twelve were held
        #   back, so the header count nobody had touched changed by itself. The
        #   population here is "no real typed number, and nothing ordered from
        #   them", which does not change when this command runs, so the same
        #   vendors are held back every time.
        candidates = [v for v in fillable
                      if v.id not in with_orders
                      and (not v.gst_number or is_dummy(v.gst_number)
                           or (legacy and is_legacy_dummy(v.gst_number)))]
        holdback = candidates[-options["holdback"]:] if options["holdback"] > 0 else []
        holdback_ids = {v.id for v in holdback}

        to_fill = [v for v in fillable
                   if not v.gst_number and v.id not in holdback_ids]
        legacy = [v for v in legacy if v.id not in holdback_ids]

        # A vendor held back this time may carry a dummy from an earlier run with
        # a smaller holdback. Clear it, or the number the header reports is not
        # the number actually held back.
        to_clear = [v for v in holdback if v.gst_number]

        unregistered = Vendor.objects.filter(is_unregistered=True).count()
        company = CompanyProfile.get_solo()

        if dry:
            blank_now = len([v for v in vendors if not v.gst_number])
            self.stdout.write(
                f"{len(vendors)} vendors. {blank_now} have no GST number.\n"
                f"  would fill      {len(to_fill)}\n"
                f"  would hold back {len(holdback)} (no orders against any of them)\n"
                f"  would clear     {len(to_clear)} dummies now inside the holdback\n"
                f"  would normalise {len(legacy)} legacy {LEGACY_DUMMY_PAN} dummies\n"
                f"  never touched, ticked unregistered: {unregistered}\n"
                f"  our own GSTIN: {company.gst_number or 'not set'} "
                f"-> would become {COMPANY_GSTIN}\n"
                f"Nothing written.")
            return

        with transaction.atomic():
            # ⚠ OURS FIRST. Until this is set, `_is_interstate()` returns False
            #   for everybody and every order prints CGST + SGST regardless of
            #   the vendor's state. Setting it before the vendors means the very
            #   first order raised after this command is already correct.
            company.gst_number = COMPANY_GSTIN
            company.save()   # derives `state` from the first two digits

            serial = 0
            filled = 0
            for vendor in to_fill:
                serial += 1
                vendor.gst_number = dummy_for(serial)
                # ⚠ `state` MUST be cleared first, or Vendor.save() sees a value
                #   already there and skips the derivation — the same trap that
                #   left vendors stateless in `po_service.approve()`. Blank it,
                #   let save() work it out, exactly like a first capture.
                vendor.state = ""
                vendor.save(update_fields=["gst_number", "state", "updated_at"])
                filled += 1

            normalised = 0
            for vendor in legacy:
                serial += 1
                vendor.gst_number = dummy_for(serial)
                vendor.state = ""
                vendor.save(update_fields=["gst_number", "state", "updated_at"])
                normalised += 1

            for vendor in to_clear:
                vendor.gst_number = ""
                vendor.state = ""
                vendor.save(update_fields=["gst_number", "state", "updated_at"])

        still_blank = Vendor.objects.filter(
            gst_number="", is_unregistered=False).count()
        away = Vendor.objects.exclude(gst_number="").exclude(
            gst_number__startswith=HOME_STATE).count()

        self.stdout.write(self.style.SUCCESS(
            f"Filled {filled} vendors with dummy GST numbers, normalised {normalised} "
            f"legacy ones.\n"
            f"Our own GSTIN is now {COMPANY_GSTIN} ({company.state}) — CGST + SGST for "
            f"Gujarat vendors, IGST for the {away} out of state.\n"
            f"⚠ {still_blank} registered vendors STILL have no GSTIN, on purpose, plus "
            f"{unregistered} ticked unregistered that never will. Nothing has been ordered "
            f"from any of them, so no approval is blocked — the count is there so the "
            f"go-live GSTIN gap stays visible on the vendor master.\n"
            f"Every number written contains {DUMMY_PAN} and is fake. "
            f"Take them away again: python manage.py seed_dummy_gstins --remove"))

    # ----------------------------------------------------------------- remove
    def remove(self, dry=False):
        """
        ⚠ MATCHES ON THE `ZZDMY` BLOCK, NOT ON "EVERY GSTIN". A real number typed
          by somebody between the two runs must survive this, or the command
          becomes a way to lose real data.
        """
        vendors = [v for v in Vendor.objects.all() if is_dummy(v.gst_number)]
        company = CompanyProfile.get_solo()
        clearing_ours = is_dummy(company.gst_number)

        if dry:
            self.stdout.write(
                f"Would clear {len(vendors)} dummy vendor GSTINs"
                f"{' and ours' if clearing_ours else ''}. Nothing written.")
            return

        with transaction.atomic():
            for vendor in vendors:
                vendor.gst_number = ""
                vendor.state = ""
                vendor.save(update_fields=["gst_number", "state", "updated_at"])
            if clearing_ours:
                company.gst_number = ""
                company.state = ""
                company.save()

        real = Vendor.objects.exclude(gst_number="").count()
        self.stdout.write(self.style.SUCCESS(
            f"Cleared {len(vendors)} dummy GSTINs"
            f"{' and our own' if clearing_ours else ''}. "
            f"{real} vendors still have a GST number — those are real, or were typed "
            f"by hand, and were left alone."))
