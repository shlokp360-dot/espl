"""
The project tab bar, and which door you came through.

>>> ANCHOR: PO-DOORWAY <<<
Saahil, on a purchase order: "if I'm going through a PO tile, ideally a BOM
should not be visible… they should only be able to review information about PO."

⚠⚠ THE BAR HAD NO PERMISSION CHECK AT ALL. It was written before roles existed
   and never revisited, so an accountant saw a BOQ tab that answers 403 and a
   site engineer saw three. The rule was already written down for the
   launchpad's tiles — "a tile can never lead to a 403" — and every one of these
   tests is that rule applied one level down.
"""
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, UserProfile
from masters.models import Vendor, VendorGroup
from projects.bom_models import PurchaseOrder
from projects.models import Project

User = get_user_model()


class ATabNeverLeadsToA403(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.project = Project.objects.create(name="Nav site", bua_sqft=D("10000"))
        group = VendorGroup.objects.create(name="Nav suppliers")
        cls.vendor = Vendor.objects.create(code="VEN-N01", name="Epsilon", phone="9000000201",
                                           group=group, gst_number="24AAAAA0000A1Z5")
        cls.order = PurchaseOrder.objects.create(
            number="PO-NAV01", project=cls.project, vendor=cls.vendor,
            status=PurchaseOrder.Status.APPROVED)

    def as_role(self, role):
        user = User.objects.create_user(username=f"nav.{role.lower()}", password="x")
        UserProfile.objects.update_or_create(
            user=user, defaults={"role": role, "must_change_password": False})
        self.client.force_login(user)
        return user

    def document(self, standalone=False):
        url = reverse("po_detail", args=[self.project.id, self.order.id])
        if standalone:
            url += "?from=register"
        return self.client.get(url)

    def tabs_on(self, response):
        """The project screens this page offers a link to."""
        page = response.content.decode()
        return {name for name, url in (
            ("boq", reverse("boq_screen", args=[self.project.id])),
            ("bom", reverse("bom_screen", args=[self.project.id])),
            ("orders", reverse("po_screen", args=[self.project.id])),
            ("projects", reverse("project_list")),
        ) if f'href="{url}"' in page}

    # ------------------------------------------------ what each role is offered

    def test_an_admin_sees_the_whole_chain(self):
        self.as_role(Role.ADMIN)
        self.assertEqual(self.tabs_on(self.document()),
                         {"boq", "bom", "orders", "projects"})

    def test_a_purchase_manager_loses_the_estimate(self):
        """They plan and they buy; the quote is not theirs."""
        self.as_role(Role.PURCHASE)
        self.assertEqual(self.tabs_on(self.document()), {"bom", "orders", "projects"})

    def test_an_accountant_is_not_offered_the_boq_or_the_bom(self):
        self.as_role(Role.ACCOUNTANT)
        self.assertEqual(self.tabs_on(self.document()), {"orders", "projects"})

    def test_a_site_engineer_gets_site_stock_where_the_bom_would_be(self):
        """
        ⚠ THIS SAID {"bom", "orders"} FOR ONE COMMIT, AND THE REWRITE IS THE
          RECORD. They reached the stock column through the buying grid until
          Saahil chose a narrow screen instead; now the BOM tab is not theirs at
          all and Site stock stands in its place. The estimate and the project
          list were never theirs.
        """
        self.as_role(Role.SITE)
        self.assertEqual(self.tabs_on(self.document()), {"orders"})
        self.assertIn(f'href="{reverse("stock_screen", args=[self.project.id])}"',
                      self.document().content.decode())

    def test_the_stock_tab_is_not_shown_to_somebody_holding_the_whole_grid(self):
        """
        ⚠ TWO DOORS TO THE SAME TWO COLUMNS IS A LONGER TAB BAR FOR NO GAIN. The
          stock screen is a subset of the BOM, so it appears only for somebody
          who cannot open the BOM.
        """
        self.as_role(Role.ADMIN)
        self.assertNotIn(f'href="{reverse("stock_screen", args=[self.project.id])}"',
                         self.document().content.decode())

    def test_every_tab_offered_actually_opens(self):
        """
        ⚠⚠ THE TEST THAT WOULD HAVE CAUGHT THE ORIGINAL FAULT. Follow every link
          the bar draws, for every role, and none of them may answer 403.
        """
        for role in (Role.ADMIN, Role.PROJECT_MANAGER, Role.PURCHASE,
                     Role.ACCOUNTANT, Role.SITE, Role.COMPLIANCE):
            with self.subTest(role=role):
                self.as_role(role)
                response = self.document()
                if response.status_code == 403:
                    continue            # they cannot open the document at all
                for name in self.tabs_on(response):
                    url = {
                        "boq": reverse("boq_screen", args=[self.project.id]),
                        "bom": reverse("bom_screen", args=[self.project.id]),
                        "orders": reverse("po_screen", args=[self.project.id]),
                        "projects": reverse("project_list"),
                    }[name]
                    self.assertNotEqual(
                        self.client.get(url).status_code, 403,
                        f"{role} was offered the {name} tab and then refused it")

    # ------------------------------------------------------------ the doorway

    def test_arriving_from_the_register_shows_no_project_tabs(self):
        self.as_role(Role.ADMIN)
        self.assertEqual(self.tabs_on(self.document(standalone=True)), set())

    def test_arriving_through_the_project_keeps_them(self):
        """Same screen, same document, same person — only the door differs."""
        self.as_role(Role.ADMIN)
        self.assertTrue(self.tabs_on(self.document()))

    def test_the_way_back_is_the_register_you_came_from(self):
        self.as_role(Role.ADMIN)
        page = self.document(standalone=True).content.decode()
        self.assertIn(f'href="{reverse("po_register")}"', page)

    def test_the_register_link_says_where_it_came_from(self):
        """The doorway is carried by the link, not guessed from a referer."""
        self.as_role(Role.ADMIN)
        page = self.client.get(reverse("po_register")).content.decode()
        self.assertIn("?from=register", page)

    def test_an_unknown_doorway_is_treated_as_the_normal_one(self):
        """Nothing hides the tabs by accident — only the register does."""
        self.as_role(Role.ADMIN)
        url = reverse("po_detail", args=[self.project.id, self.order.id]) + "?from=banana"
        self.assertTrue(self.tabs_on(self.client.get(url)))
