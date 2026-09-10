"""
The dummy GSTIN seeder, and every way it could do damage.

>>> ANCHOR: DUMMY-GSTINS <<<
Saahil's call, 16 Aug: real GSTINs are collected over the project's life, so put
fake ones in now and stop approval being blocked on a test database.

⚠⚠ WHAT THESE TESTS ARE REALLY GUARDING is not that the command works. It is
   that a command which writes FAKE TAX NUMBERS cannot reach a real vendor
   record — that it refuses on production, never overwrites a number somebody
   typed, and that `--remove` takes away its own rows and nothing else. The
   convenience is worth very little; those three properties are the whole cost
   of having it at all.

⚠ THE HARD BLOCK IS NOT TESTED AWAY. `approve()` is unchanged, and one test here
  asserts it still refuses a vendor the seeder deliberately held back.
"""
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import Role, UserProfile
from masters.models import (Activity, CompanyProfile, DocumentType, Material,
                            MaterialGroup, Vendor, VendorGroup, gstin_format)
from projects import po_service
from projects.bom_models import Bom, BomLine, PurchaseOrder, PurchaseOrderLine
from projects.management.commands.seed_dummy_gstins import (
    COMPANY_GSTIN, DUMMY_PAN, dummy_for, is_dummy)
from projects.models import Project

User = get_user_model()


class DummyGstinFixture(TestCase):
    """
    Thirty vendors: most blank, one real, one legacy dummy, one unregistered,
    and one that has an order against it so it can never be held back.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="zq.gstin", password="x")
        UserProfile.objects.update_or_create(
            user=cls.admin, defaults={"role": Role.ADMIN, "must_change_password": False})

        # ⚠ BUG 19 — migration 0003 seeds the real activity master. ZQ* is safe.
        cls.activity = Activity.objects.create(abbreviation="ZQG", name="GSTIN test activity",
                                               rate=D("100"), sort_order=907)
        group = MaterialGroup.objects.create(code="ZQG", name="GSTIN test group")
        cls.material = Material.objects.create(
            code="ZQG-ZQG-001", name="ZQ TEST CEMENT", group=group,
            home_activity=cls.activity, uom="Bag",
            estimation_rate=D("400"), gst_percent=D("28"))
        cls.vendor_group = VendorGroup.objects.create(name="ZQ GSTIN suppliers")

        # Twenty-five plain vendors with no GST number and no orders.
        cls.blanks = [
            Vendor.objects.create(code=f"VEN-Z{n:02d}", name=f"ZQ Blank Supplier {n}",
                                  phone=f"90000{n:05d}", group=cls.vendor_group)
            for n in range(1, 26)
        ]

        # One with a genuine-looking number somebody typed. Must never move.
        cls.real = Vendor.objects.create(
            code="VEN-Z90", name="ZQ Real Supplier", phone="9000090001",
            group=cls.vendor_group, gst_number="24AAAAA0000A1Z5")

        # One of the four early dummies built from the help text's own example.
        cls.legacy = Vendor.objects.create(
            code="VEN-Z91", name="ZQ Legacy Dummy", phone="9000090002",
            group=cls.vendor_group, gst_number="07ABCDE1234F1Z5")

        # The hardware shop. Has no GSTIN and never will — must stay blank.
        cls.unregistered = Vendor.objects.create(
            code="VEN-Z92", name="ZQ Street Supplier", phone="9000090003",
            group=cls.vendor_group, is_unregistered=True)

        # One blank vendor WITH an order against it. This is the one the
        # holdback must never choose, because it is exactly the block we are
        # here to clear.
        cls.ordered_from = Vendor.objects.create(
            code="VEN-Z93", name="ZQ Ordered Supplier", phone="9000090004",
            group=cls.vendor_group)

        cls.project = Project.objects.create(name="ZQ GSTIN site", bua_sqft=D("10000"))
        cls.bom = Bom.objects.create(project=cls.project, generated_by=cls.admin)
        cls.line = BomLine.objects.create(
            bom=cls.bom, activity=cls.activity, material=cls.material,
            planned_qty=D("100"), vendor=cls.ordered_from, sort_order=1)
        cls.order = PurchaseOrder.objects.create(
            number="ZQG-0001", project=cls.project, vendor=cls.ordered_from,
            document_type=DocumentType.PO, created_by=cls.admin)
        PurchaseOrderLine.objects.create(
            purchase_order=cls.order, bom_line=cls.line, quantity=D("10"),
            rate=D("340"), discount_pct=D("0"), gst_percent=D("28"))


class TheNumbersItWritesAreValidAndObviouslyFake(TestCase):

    def test_every_generated_number_passes_the_real_validator(self):
        """
        ⚠ NOT A HAND-CHECKED PATTERN. `gstin_format` is the same validator that
          `approve()` runs, so if these did not pass, the command would fill the
          database with numbers approval would then reject.
        """
        for serial in range(1, 200):
            gstin_format(dummy_for(serial))   # raises ValidationError if wrong

    def test_our_own_number_passes_too(self):
        gstin_format(COMPANY_GSTIN)

    def test_every_number_carries_the_dummy_marker(self):
        """The marker is what makes them findable, and what --remove matches."""
        for serial in range(1, 200):
            self.assertEqual(dummy_for(serial)[2:7], DUMMY_PAN)

    def test_no_two_vendors_share_a_number(self):
        """
        One GSTIN across the whole master would be indistinguishable in any
        report grouped by tax registration.
        """
        generated = [dummy_for(serial) for serial in range(1, 200)]
        self.assertEqual(len(generated), len(set(generated)))

    def test_some_are_out_of_state_so_the_igst_branch_can_fire(self):
        """
        ⚠ ALL-GUJARAT WOULD LEAVE `_is_interstate()` UNTESTED, and that branch
          decides CGST + SGST versus IGST on a document actually sent.
        """
        states = {dummy_for(serial)[:2] for serial in range(1, 100)}
        self.assertIn("24", states)
        self.assertGreater(len(states), 1, "no vendor would ever attract IGST")

    def test_a_real_looking_number_is_not_mistaken_for_a_dummy(self):
        self.assertFalse(is_dummy("24AAAAA0000A1Z5"))
        self.assertFalse(is_dummy("07ABCDE1234F1Z5"))
        self.assertFalse(is_dummy(""))
        self.assertTrue(is_dummy(dummy_for(7)))


class ItRefusesToRunOnProduction(DummyGstinFixture):

    @override_settings(DEBUG=False)
    def test_debug_false_is_refused(self):
        """
        ⚠⚠ THE GUARD THAT MATTERS. Everything else is tidiness; this is the line
           between a convenience and a fake GSTIN on a filed return.
        """
        with self.assertRaises(CommandError) as refused:
            call_command("seed_dummy_gstins")
        self.assertIn("DEBUG is False", str(refused.exception))

    @override_settings(DEBUG=False)
    def test_nothing_is_written_when_it_refuses(self):
        with self.assertRaises(CommandError):
            call_command("seed_dummy_gstins")
        self.assertEqual(Vendor.objects.exclude(gst_number="").count(), 2)

    @override_settings(DEBUG=False)
    def test_remove_is_refused_on_production_too(self):
        """Clearing GSTINs on production is destructive in its own right."""
        with self.assertRaises(CommandError):
            call_command("seed_dummy_gstins", "--remove")


@override_settings(DEBUG=True)
class FillingLeavesRealDataAlone(DummyGstinFixture):

    def test_a_typed_number_is_never_overwritten(self):
        call_command("seed_dummy_gstins", verbosity=0)
        self.real.refresh_from_db()
        self.assertEqual(self.real.gst_number, "24AAAAA0000A1Z5")

    def test_an_unregistered_vendor_is_left_blank(self):
        """
        The tick means "has no GST registration and never will". Writing a
        number onto that vendor would contradict the flag and raise their lines
        from 0% to the material rate.
        """
        call_command("seed_dummy_gstins", verbosity=0)
        self.unregistered.refresh_from_db()
        self.assertEqual(self.unregistered.gst_number, "")

    def test_the_legacy_dummy_is_normalised_onto_the_marked_pattern(self):
        """
        `07ABCDE1234F1Z5` is indistinguishable from a real number, which is the
        whole problem. After this there is exactly one answer to "which are fake".
        """
        call_command("seed_dummy_gstins", "--holdback", "0", verbosity=0)
        self.legacy.refresh_from_db()
        self.assertTrue(is_dummy(self.legacy.gst_number))

    def test_a_legacy_dummy_inside_the_holdback_is_cleared_not_renumbered(self):
        """
        ⚠ A HELD-BACK VENDOR MUST END BLANK, whatever it carried before. Clearing
          a fake number loses nothing, and leaving it would mean the header
          reported a smaller gap than was actually held back.
        """
        call_command("seed_dummy_gstins", "--holdback", "20", verbosity=0)
        self.legacy.refresh_from_db()
        self.assertEqual(self.legacy.gst_number, "")

    def test_the_legacy_dummy_can_be_left_alone_on_request(self):
        call_command("seed_dummy_gstins", "--no-normalise-legacy", verbosity=0)
        self.legacy.refresh_from_db()
        self.assertEqual(self.legacy.gst_number, "07ABCDE1234F1Z5")

    def test_a_dry_run_writes_nothing(self):
        call_command("seed_dummy_gstins", "--dry-run", verbosity=0)
        self.assertEqual(Vendor.objects.exclude(gst_number="").count(), 2)
        self.assertEqual(CompanyProfile.get_solo().gst_number, "")


@override_settings(DEBUG=True)
class TheHoldbackKeepsTheCounterHonest(DummyGstinFixture):

    def test_some_vendors_are_left_blank_on_purpose(self):
        """
        ⚠ THE VENDOR MASTER HEADER COUNTS "N without a GSTIN" and that number
          ties straight to the go-live gap. Filling everything would make it read
          0 and hide the thing it exists to show.
        """
        call_command("seed_dummy_gstins", "--holdback", "5", verbosity=0)
        blank = Vendor.objects.filter(gst_number="", is_unregistered=False)
        self.assertEqual(blank.count(), 5)

    def test_an_unregistered_vendor_does_not_consume_a_holdback_slot(self):
        """
        ⚠ IT IS ALREADY PERMANENTLY BLANK. Letting it count as one of the held
          back made the number a lie — ask for five and four were actually held.
        """
        call_command("seed_dummy_gstins", "--holdback", "5", verbosity=0)
        self.unregistered.refresh_from_db()
        self.assertEqual(self.unregistered.gst_number, "")
        self.assertEqual(
            Vendor.objects.filter(gst_number="", is_unregistered=False).count(), 5)

    def test_shrinking_the_holdback_fills_the_ones_released(self):
        call_command("seed_dummy_gstins", "--holdback", "10", verbosity=0)
        call_command("seed_dummy_gstins", "--holdback", "3", verbosity=0)
        self.assertEqual(
            Vendor.objects.filter(gst_number="", is_unregistered=False).count(), 3)

    def test_growing_the_holdback_clears_the_ones_taken_back(self):
        """
        ⚠ A VENDOR HELD BACK THIS TIME MAY CARRY A DUMMY FROM LAST TIME. Leaving
          it would mean the header reports a smaller gap than is actually held.
        """
        call_command("seed_dummy_gstins", "--holdback", "3", verbosity=0)
        call_command("seed_dummy_gstins", "--holdback", "10", verbosity=0)
        self.assertEqual(
            Vendor.objects.filter(gst_number="", is_unregistered=False).count(), 10)

    def test_a_vendor_with_an_order_is_never_held_back(self):
        """
        ⚠⚠ HOLDING BACK A VENDOR WE HAVE ORDERED FROM would recreate the exact
           block this command exists to clear, and it would look like the command
           had simply not worked.
        """
        call_command("seed_dummy_gstins", "--holdback", "20", verbosity=0)
        self.ordered_from.refresh_from_db()
        self.assertTrue(is_dummy(self.ordered_from.gst_number))

    def test_the_holdback_is_deterministic(self):
        """A second run holds back the same rows, not a different sample."""
        call_command("seed_dummy_gstins", "--holdback", "5", verbosity=0)
        first = set(Vendor.objects.filter(gst_number="").values_list("id", flat=True))
        call_command("seed_dummy_gstins", "--remove", verbosity=0)
        call_command("seed_dummy_gstins", "--holdback", "5", verbosity=0)
        second = set(Vendor.objects.filter(gst_number="").values_list("id", flat=True))
        self.assertEqual(first, second)

    def test_holdback_zero_fills_everything_available(self):
        call_command("seed_dummy_gstins", "--holdback", "0", verbosity=0)
        self.assertEqual(
            Vendor.objects.filter(gst_number="", is_unregistered=False).count(), 0)


@override_settings(DEBUG=True)
class OurOwnNumberIsSetAndTheStateIsDerived(DummyGstinFixture):

    def test_the_company_gstin_is_filled(self):
        """
        ⚠⚠ WITHOUT THIS, `_is_interstate()` RETURNS FALSE FOR EVERYBODY and every
           order prints CGST + SGST regardless of where the vendor is. Filling
           vendor numbers alone would give a database where approval works and
           the tax split is silently always-local — worse than being blocked,
           because it looks right.
        """
        call_command("seed_dummy_gstins", verbosity=0)
        self.assertEqual(CompanyProfile.get_solo().gst_number, COMPANY_GSTIN)

    def test_our_state_is_derived_not_typed(self):
        call_command("seed_dummy_gstins", verbosity=0)
        self.assertEqual(CompanyProfile.get_solo().state, "Gujarat")

    def test_each_vendor_state_is_derived_from_its_own_first_two_digits(self):
        """
        ⚠ THE TRAP FROM `po_service.approve()`: `state` is only derived when it
          is blank, so a vendor carrying a stale state would keep it and the PDF
          would print the wrong tax lines. The command blanks it first.
        """
        call_command("seed_dummy_gstins", verbosity=0)
        for vendor in Vendor.objects.exclude(gst_number=""):
            if is_dummy(vendor.gst_number):
                self.assertTrue(vendor.state, f"{vendor.code} has a GSTIN but no state")

    def test_both_tax_paths_exist_in_the_result(self):
        call_command("seed_dummy_gstins", "--holdback", "0", verbosity=0)
        dummies = [v for v in Vendor.objects.all() if is_dummy(v.gst_number)]
        home = [v for v in dummies if v.gst_number[:2] == "24"]
        away = [v for v in dummies if v.gst_number[:2] != "24"]
        self.assertTrue(home, "nothing would print CGST + SGST")
        self.assertTrue(away, "nothing would print IGST")


@override_settings(DEBUG=True)
class ApprovalIsUnblockedButTheRuleIsUnchanged(DummyGstinFixture):

    def test_an_order_can_be_approved_after_seeding(self):
        call_command("seed_dummy_gstins", verbosity=0)

        # ⚠ BUG 5's SHAPE — the command updated the vendor ROW, but `self.order`
        #   is a class-level object whose `.vendor` was cached before that, so it
        #   still reports a blank GSTIN and approval refuses. Re-reading the order
        #   is not a workaround: it is exactly what the view does, which loads the
        #   order fresh on every request.
        order = PurchaseOrder.objects.get(pk=self.order.pk)
        po_service.approve(order, user=self.admin)
        order.refresh_from_db()
        self.assertEqual(order.status, PurchaseOrder.Status.APPROVED)

    def test_the_vendor_on_that_order_really_was_filled(self):
        """The assertion above would also pass if the block had been removed."""
        call_command("seed_dummy_gstins", verbosity=0)
        self.ordered_from.refresh_from_db()
        self.assertTrue(is_dummy(self.ordered_from.gst_number))

    def test_a_held_back_vendor_is_still_refused(self):
        """
        ⚠⚠ THE HARD BLOCK IS DATA-SATISFIED, NOT WEAKENED. Not one line of
           `approve()` changed, and this is the assertion that says so.
        """
        call_command("seed_dummy_gstins", "--holdback", "5", verbosity=0)
        held = Vendor.objects.filter(gst_number="", is_unregistered=False).first()
        self.assertIsNotNone(held)

        line = BomLine.objects.create(
            bom=self.bom, activity=self.activity, material=self.material,
            planned_qty=D("10"), vendor=held, sort_order=2)
        order = PurchaseOrder.objects.create(
            number="ZQG-0002", project=self.project, vendor=held,
            document_type=DocumentType.PO, created_by=self.admin)
        PurchaseOrderLine.objects.create(
            purchase_order=order, bom_line=line, quantity=D("1"),
            rate=D("10"), discount_pct=D("0"), gst_percent=D("28"))

        with self.assertRaises(po_service.POError) as refused:
            po_service.approve(order, user=self.admin)
        self.assertIn("no GST number", str(refused.exception))


@override_settings(DEBUG=True)
class RemoveTakesAwayItsOwnRowsAndNothingElse(DummyGstinFixture):

    def test_a_real_number_survives_the_removal(self):
        """
        ⚠⚠ IF THIS MATCHED ON "EVERY GSTIN" the command would be a way to lose
           real data — including numbers collected between the two runs, which is
           precisely what happens over the life of this project.
        """
        call_command("seed_dummy_gstins", verbosity=0)
        call_command("seed_dummy_gstins", "--remove", verbosity=0)
        self.real.refresh_from_db()
        self.assertEqual(self.real.gst_number, "24AAAAA0000A1Z5")

    def test_a_number_typed_between_the_two_runs_survives(self):
        call_command("seed_dummy_gstins", verbosity=0)
        collected = Vendor.objects.exclude(id=self.real.id).filter(
            gst_number__contains=DUMMY_PAN).first()
        collected.gst_number = "24ZZZZZ9999Z1Z5"
        collected.state = ""
        collected.save(update_fields=["gst_number", "state", "updated_at"])

        call_command("seed_dummy_gstins", "--remove", verbosity=0)
        collected.refresh_from_db()
        self.assertEqual(collected.gst_number, "24ZZZZZ9999Z1Z5")

    def test_every_dummy_is_cleared(self):
        call_command("seed_dummy_gstins", verbosity=0)
        call_command("seed_dummy_gstins", "--remove", verbosity=0)
        self.assertFalse([v for v in Vendor.objects.all() if is_dummy(v.gst_number)])

    def test_our_own_dummy_is_cleared_too(self):
        call_command("seed_dummy_gstins", verbosity=0)
        call_command("seed_dummy_gstins", "--remove", verbosity=0)
        self.assertEqual(CompanyProfile.get_solo().gst_number, "")

    def test_a_real_company_gstin_survives_the_removal(self):
        """The day he types the real one, --remove must not take it away."""
        company = CompanyProfile.get_solo()
        company.gst_number = "24REALX1234R1Z5"
        company.save()
        call_command("seed_dummy_gstins", "--remove", verbosity=0)
        self.assertEqual(CompanyProfile.get_solo().gst_number, "24REALX1234R1Z5")

    def test_removing_twice_is_harmless(self):
        call_command("seed_dummy_gstins", verbosity=0)
        call_command("seed_dummy_gstins", "--remove", verbosity=0)
        call_command("seed_dummy_gstins", "--remove", verbosity=0)
        self.assertEqual(Vendor.objects.exclude(gst_number="").count(), 1)
