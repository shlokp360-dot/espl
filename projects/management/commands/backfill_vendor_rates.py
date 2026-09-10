"""
Populate the vendor/material rate master from orders already approved.

>>> ANCHOR: VENDOR-RATE-CAPTURE <<<
The write-back on approval was described in the model from the beginning and
never implemented, so on any database in use there are approved, delivered and
paid orders whose rates were never recorded. Without this the screen stays empty
until somebody happens to approve the next order, and Saahil's three live
documents would prove nothing.

⚠⚠ OLDEST FIRST, SO THE NEWEST ORDER WINS. Each write replaces the row for its
   vendor and material, so processing in an arbitrary order would leave whichever
   document happened to come last standing — and "last processed" is not "most
   recent". Ordered by approval date, then by id for documents approved in the
   same second.

⚠ DRAFTS ARE NOT INCLUDED, exactly as on the live path. A draft is a working
  document that may never be sent; a rate nobody committed to is not evidence.

⚠ SAFE TO RUN TWICE. Every write is an update_or_create on the same unique pair,
  so a second run recomputes the same rows to the same values.

    python manage.py backfill_vendor_rates --dry-run
    python manage.py backfill_vendor_rates
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from masters.models import VendorRate
from projects.bom_models import PurchaseOrder
from projects.po_service import capture_vendor_rates


class Command(BaseCommand):
    help = "Capture vendor rates from every order already approved, oldest first."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Count what would be written and change nothing.")

    def handle(self, *args, **options):
        committed = [PurchaseOrder.Status.APPROVED,
                     PurchaseOrder.Status.DELIVERED,
                     PurchaseOrder.Status.PAID]

        # ⚠ `approved_at` CAN BE NULL on an old row, and NULLs sort first in
        #   SQLite and last in PostgreSQL — the two databases would disagree
        #   about which order wins. Ordering by id as well makes it deterministic
        #   on both. (Bug 2's shape: the same query, two answers.)
        orders = (PurchaseOrder.objects
                  .filter(status__in=committed)
                  .select_related("vendor")
                  .order_by("approved_at", "id"))

        before = VendorRate.objects.count()
        total = orders.count()

        if options["dry_run"]:
            lines = sum(order.lines.count() for order in orders)
            self.stdout.write(
                f"{total} approved-or-later orders carrying {lines} lines.\n"
                f"The rate master holds {before} rows now. Nothing written.")
            return

        with transaction.atomic():
            for order in orders:
                capture_vendor_rates(order)

        after = VendorRate.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"Read {total} orders. The rate master went from {before} to {after} rows "
            f"({after - before} new; the rest were replaced with a later rate)."))
