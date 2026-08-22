"""
THE AGREED TABLE, AS A TEST.

⚠ THIS FILE IS THE MATRIX SAAHIL FILLED IN WITH THE CUSTOMER, WRITTEN OUT AGAIN
  BY HAND. That duplication is the point. `accounts/perms.py` is the
  implementation; this is the specification, transcribed from the table on the
  screen, and a change that alters behaviour has to be made in both places by
  somebody who noticed they were doing it.

⚠ IT WALKS EVERY ROLE AGAINST EVERY SCREEN, not a sample. Six roles by roughly
  thirty addresses is 180 assertions nobody would write out, and exactly the
  kind of thing that goes stale the moment it is written by hand.
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from accounts.testing import AuthedTestCase

A, PM, PUR, ACC, SITE, COMP = (
    Role.ADMIN, Role.PROJECT_MANAGER, Role.PURCHASE,
    Role.ACCOUNTANT, Role.SITE, Role.COMPLIANCE,
)
EVERYBODY = {A, PM, PUR, ACC, SITE, COMP}

#: (url name, needs project id, roles that may GET it)
#: Transcribed from the agreed table, row by row.
SCREENS = [
    ("launchpad",        False, EVERYBODY),
    # ⚠ ANCHOR: INFO-PANELS — Admin alone. See the note against panel_text_save.
    ("panel_text",       False, {A}),
    ("project_list",     False, {A, PM, PUR, ACC}),
    ("project_new",      False, {A, PM}),
    ("boq_screen",       True,  {A, PM}),
    # >>> ANCHOR: BOQ-PDF <<< — reads the estimate, so it reads like boq.view.
    ("boq_pdf",          True,  {A, PM}),
    # ⚠ SITE WAS ADDED HERE FOR ONE COMMIT AND THEN TAKEN BACK OUT. Reading the
    #   BOM was how the engineer first reached the stock column; Saahil chose a
    #   narrow screen of their own instead, so the buying grid is refused to
    #   them again. `stock_screen` below is what they get.
    ("bom_screen",       True,  {A, PM, PUR}),
    ("stock_screen",     True,  {A, PM, PUR, SITE}),
    ("po_screen",        True,  {A, PM, PUR, ACC, SITE}),
    ("po_preview",       True,  {A, PM, PUR}),
    ("po_register",      False, {A, PM, PUR, ACC, SITE}),
    ("master_data",      False, {A, PM, PUR, ACC}),
    ("material_list",    False, {A, PM, PUR, ACC}),
    ("vendor_list",      False, {A, PM, PUR, ACC}),
    ("material_new",     False, {A, PM, PUR, ACC}),
    ("company_profile",  False, {A}),
    ("rate_defaults",    False, {A}),
    ("user_list",        False, {A}),
    # ⚠ EVERYBODY READS THE BOARD. Creating and assigning is `tasks.manage` and
    #   is checked against the three POST addresses below — the same split as
    #   the purchase order register, where Site may look at every value and may
    #   not export the file.
    ("task_board",       False, EVERYBODY),
    ("task_mine",        False, EVERYBODY),
    ("task_schedule",    False, EVERYBODY),
    # ⚠ Purchase is the one role NOT on this row — the agreed table, and the
    #   only role with no reason to be asked for a municipal document.
    ("compliance_home",            False, {A, PM, ACC, SITE, COMP}),
    ("compliance_project_default", False, {A, PM, ACC, SITE, COMP}),
    ("compliance_timeline",        False, {A, PM, ACC, SITE, COMP}),
    # ⚠ EDITING THE CHECKLIST IS NOT READING IT. One new line makes every project
    #   non-compliant at once, so the master is Admin and Compliance only.
    ("compliance_master",          False, {A, COMP}),
    ("task_people",      False, {A, PM}),
    # ⚠ Changing the plan. There is no header with id 1 here, so an allowed role
    #   gets a 404 — which is the right answer and is NOT a 403. This test asks
    #   one question only: who is refused. What the screen then does with a real
    #   row is tasks/tests.py's job.
    ("task_header_edit",  True,  {A, PM}),
    # ⚠ THE ONE TASK SCREEN NOT EVERYBODY OPENS. Whether an engineer sees
    #   everybody's delays was left open in the design session; manager-only is
    #   the reversible answer, and their own late rows are on their own screen.
    ("task_delay_log",   False, {A, PM}),
]

#: POST-only actions, checked for the refusal rather than the whole flow.
ACTIONS = [
    # ⚠ THIS ROW SAID {A, PM, PUR} UNTIL THE SITE ENGINEER GOT THE STOCK COLUMN,
    #   and the rewrite is the record. The DOOR is now open to them, because the
    #   grid is one form and their stock figure arrives in the same POST as
    #   everything else. What they may WRITE is decided field by field inside
    #   the view — see ANCHOR: BOM-STOCK-ONLY, and the tests in
    #   projects/test_bom_stock.py which assert that a site engineer's POST
    #   moves the stock and leaves the rates, vendors and quantities alone.
    #
    #   ⚠ SO THIS TABLE NO LONGER TELLS THE WHOLE STORY FOR THIS ONE ROW. That
    #     is the price of a single form serving two roles, and it is why the
    #     field-level test exists rather than being optional.
    ("bom_save",            True,  {A, PM, PUR, SITE}),
    ("stock_save",          True,  {A, PM, PUR, SITE}),
    ("bom_generate",        True,  {A, PM, PUR}),
    ("bom_post_pos",        True,  {A, PM, PUR}),
    ("boq_save",            True,  {A, PM}),
    ("project_status",      True,  {A, PM}),
    ("material_import",     False, {A, PM, PUR, ACC}),
    ("po_register_excel",   False, {A, PM, PUR, ACC}),
    ("po_register_zip",     False, {A, PM, PUR, ACC}),
    ("task_header_new",     False, {A, PM}),
    ("task_subtask_new",    False, {A, PM}),
    # ⚠ `task_milestone_new` WAS REMOVED WITH THE MODEL. A milestone is a
    #   header task now, so `task_header_new` above is the same act.
    # ⚠ Reopening a tick is a manager's act. Done and Blocked are NOT listed
    #   here on purpose: every role holds `tasks.mine`, so there is no role for
    #   this test to refuse — what stops one person ticking another's row is the
    #   assignee check in the view, and tasks/tests.py is where that is proved.
    ("task_subtask_reopen", True,  {A, PM}),
    ("task_subtasks_bulk",  False, {A, PM}),
    # ⚠ ANCHOR: INFO-PANELS — writing the Gujarati on the ⓘ panels. ADMIN ALONE,
    #   and deliberately narrower than `masters.edit`, which PM, Purchase and
    #   Accountant all hold. This is what the whole company reads as
    #   instructions, in a language most of the office cannot check.
    ("panel_text_save",     "bom", {A}),
]


class TheMatrixHolds(AuthedTestCase):
    """Every role, against every screen, exactly as agreed."""

    def setUp(self):
        super().setUp()
        # ⚠ ".person" ON THE END, because AuthedTestCase has already created the
        #   user ID "admin" to sign the client in with. Without it the Admin row
        #   here collides with that one and every matrix test dies on a UNIQUE
        #   constraint rather than on anything to do with permissions.
        self.people = {role: self.make_user(f"{role}.person", role=role,
                                            name=f"{role} person")
                       for role in EVERYBODY}

    def as_role(self, role):
        self.client.force_login(self.people[role])

    @staticmethod
    def address(name, arg):
        """
        ⚠ THE SECOND COLUMN IS "the argument, if any". False means none, True
          means a project id, and a string is used as it stands — which is what
          `panel_text_save` needs, because its argument is a panel key rather
          than a number.
        """
        if arg is False:
            return reverse(name)
        return reverse(name, args=[1 if arg is True else arg])

    def test_every_screen_answers_the_right_roles(self):
        for name, needs_project, allowed in SCREENS:
            url = self.address(name, needs_project)
            for role in EVERYBODY:
                self.as_role(role)
                status = self.client.get(url).status_code
                if role in allowed:
                    self.assertNotEqual(
                        status, 403,
                        f"{role} was refused {name}, and the agreed table says they may open it")
                else:
                    self.assertEqual(
                        status, 403,
                        f"{role} opened {name} with {status} — the agreed table says they may not")

    def test_every_action_refuses_the_right_roles(self):
        for name, needs_project, allowed in ACTIONS:
            url = self.address(name, needs_project)
            for role in EVERYBODY:
                if role in allowed:
                    continue      # the happy path belongs with the screen's own tests
                self.as_role(role)
                self.assertEqual(
                    self.client.post(url).status_code, 403,
                    f"{role} was allowed to post {name}, and the agreed table says otherwise")


class TheLaunchpadShowsOnlyWhatWorks(AuthedTestCase):
    """
    ⚠ A TILE THAT LEADS TO A 403 IS WORSE THAN NO TILE. It looks like a fault in
      the system rather than a rule of the business, and the person clicking it
      has no way to tell the difference.
    """

    def setUp(self):
        super().setUp()
        self.people = {role: self.make_user(f"{role}.person", role=role)
                       for role in EVERYBODY}

    def tiles_seen(self, role):
        self.client.force_login(self.people[role])
        return {tile["key"] for tile in self.client.get(reverse("launchpad")).context["tiles"]}

    def test_a_site_engineer_sees_orders_and_not_master_data(self):
        seen = self.tiles_seen(SITE)
        self.assertIn("orders", seen)
        self.assertNotIn("masters", seen)
        self.assertNotIn("projects", seen)

    def test_an_accountant_sees_projects_orders_and_masters(self):
        seen = self.tiles_seen(ACC)
        self.assertLessEqual({"projects", "orders", "masters"}, seen)
        self.assertNotIn("analytics", seen)

    def test_only_an_admin_sees_analytics(self):
        self.assertIn("analytics", self.tiles_seen(A))
        for role in (PM, PUR, ACC, SITE, COMP):
            self.assertNotIn("analytics", self.tiles_seen(role))

    def test_compliance_now_has_the_module_they_exist_for(self):
        """
        ⚠ THIS TEST HAS BEEN REWRITTEN TWICE AND BOTH REWRITES ARE THE RECORD OF
        A PROMISE BEING KEPT.

        It began as "compliance has almost nothing until their module exists" —
        a role that could sign in and see one greyed tile. Task management went
        live under them, and now their own module has. The set below is the
        whole of what a Compliance user sees, and it is finally the right two.
        """
        self.assertEqual(self.tiles_seen(COMP), {"tasks", "compliance"})

    def test_everybody_can_reach_a_compliance_document(self):
        # ⚠ THE WIDEST READ IN THE SYSTEM, on purpose: a site engineer standing
        #   in front of an inspector needs the labour licence on their phone.
        for role in (A, PM, ACC, SITE, COMP):
            self.assertIn("compliance", self.tiles_seen(role), role)
        self.assertNotIn("compliance", self.tiles_seen(PUR))

    def test_every_tile_shown_can_actually_be_opened(self):
        for role in EVERYBODY:
            self.client.force_login(self.people[role])
            response = self.client.get(reverse("launchpad"))
            for tile in response.context["tiles"]:
                if not tile["live"]:
                    continue
                status = self.client.get(tile["url"]).status_code
                self.assertNotEqual(
                    status, 403,
                    f"{role} is shown the {tile['key']} tile and then refused at {tile['url']}")


class MasterDataShowsOnlyWhatTheRoleMayTouch(AuthedTestCase):
    def setUp(self):
        super().setUp()
        self.purchase = self.make_user("pur", role=PUR)

    def test_a_purchase_manager_sees_materials_but_not_the_company_or_users(self):
        """
        ⚠ THE ENTRIES CHANGED SHAPE WHEN MASTER DATA WAS RESTRUCTURED, and the
          rewrite is the record. `rate_defaults` is gone — the company's ₹/sqft
          per construction activity was never company data and now lives on the
          activity master, which a purchase manager may open.
        """
        self.client.force_login(self.purchase)
        body = self.client.get(reverse("master_data")).content.decode()
        self.assertIn(reverse("materials_home"), body)
        self.assertIn(reverse("vendors_home"), body)
        self.assertIn(reverse("activity_master"), body)
        self.assertNotIn(reverse("company_profile"), body)
        self.assertNotIn(reverse("user_list"), body)

    def test_an_admin_sees_all_five(self):
        body = self.client.get(reverse("master_data")).content.decode()
        for name in ("materials_home", "vendors_home", "activity_master",
                     "company_profile", "user_list"):
            self.assertIn(reverse(name), body)

    def test_nothing_on_the_page_opens_django_admin(self):
        """
        ⚠⚠ THE POINT OF THE RESTRUCTURE. Saahil found the Units of measure tile
          dropping him into generic scaffolding — "the UOM tile still shows and
          opens up Django, I could not see any UI for that". Five tables gained
          screens of their own; none of them may quietly go back.
        """
        body = self.client.get(reverse("master_data")).content.decode()
        self.assertNotIn("/admin/", body.split("<header>")[-1].split("</header>")[-1])


class TheThreeTransitionsAreThreePermissions(AuthedTestCase):
    """
    Approve, Delivered and Paid are one button row and three different people.

    ⚠ AND THE BULK BOX MUST AGREE WITH THE DOCUMENT. Saahil's rule: a Purchase
      manager who cannot mark one document Paid must not be able to mark twenty.
    """

    def setUp(self):
        super().setUp()
        self.purchase = self.make_user("pur", role=PUR)
        self.accountant = self.make_user("acc", role=ACC)
        self.site = self.make_user("site", role=SITE)

    def bulk(self, who, target):
        self.client.force_login(who)
        return self.client.post(reverse("po_register_advance"), {"to": target}).status_code

    def test_purchase_may_deliver_in_bulk_but_not_pay(self):
        self.assertEqual(self.bulk(self.purchase, "paid"), 403)
        self.assertNotEqual(self.bulk(self.purchase, "delivered"), 403)

    def test_an_accountant_may_pay_in_bulk_but_not_deliver(self):
        self.assertEqual(self.bulk(self.accountant, "delivered"), 403)
        self.assertNotEqual(self.bulk(self.accountant, "paid"), 403)

    def test_a_site_engineer_may_deliver_and_nothing_else(self):
        self.assertEqual(self.bulk(self.site, "paid"), 403)
        self.assertNotEqual(self.bulk(self.site, "delivered"), 403)

    def test_nobody_can_approve_in_bulk_whatever_their_role(self):
        # ⚠ NO BULK APPROVE, for anybody, ever. It locks permanently and
        #   hard-blocks without a GSTIN; it belongs on the document.
        self.client.force_login(self.user)          # an Admin
        response = self.client.post(reverse("po_register_advance"), {"to": "approved"})
        self.assertNotEqual(response.status_code, 200)
