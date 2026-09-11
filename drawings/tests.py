"""
What the Drawings repository has to keep being true.

⚠ THE THREE THAT MATTER MOST, all about the record:
  a revision is never overwritten, a file is never reachable without the
  permission check, and a completed project's file is kept and still accepts
  uploads. Everything else on these screens is convenience.
"""
import re
import shutil
import tempfile
from datetime import date
from decimal import Decimal as D

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Role
from accounts.testing import AuthedTestCase
from compliance.models import ComplianceDocument, ComplianceItem, ComplianceTitle, ComplianceType
from drawings import status
from drawings.models import Architect, Drawing, DrawingGroup, DrawingInUse, DrawingRevision
from drawings.panels import PANELS
from projects.models import Project

MEDIA = tempfile.mkdtemp()


def a_pdf(name="ZQ-plan.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 not really a pdf", content_type="application/pdf")


@override_settings(MEDIA_ROOT=MEDIA)
class DrawingsCase(AuthedTestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.project = Project.objects.create(
            name="ZQ Bhudarpura", bua_sqft=D("26545"), status=Project.Status.WON)
        self.other = Project.objects.create(
            name="ZQ Other site", bua_sqft=D("10000"), status=Project.Status.WON)
        self.arc = DrawingGroup.objects.get(code="ARC")
        self.str_ = DrawingGroup.objects.get(code="STR")
        self.architect = Architect.objects.create(name="ZQ Architect", firm="ZQ Studio",
                                                  phone="9900000001")
        self.drawing = Drawing.objects.create(
            project=self.project, group=self.arc, number="ZQ-A-101",
            title="Ground floor plan", architect=self.architect, created_by=self.user)

    def revision(self, drawing=None, label="R0", **extra):
        drawing = drawing or self.drawing
        return DrawingRevision.objects.create(
            drawing=drawing, label=label, file=a_pdf(), original_name=f"{label}.pdf",
            uploaded_by=self.user, **extra)

    def upload(self, drawing=None, label="R0", follow=False, **extra):
        drawing = drawing or self.drawing
        data = {"file": a_pdf(), "label": label}
        data.update(extra)
        return self.client.post(
            reverse("drawings_upload", args=[self.project.pk, drawing.pk]), data, follow=follow)

    def queries_for(self, url):
        """How many queries one GET costs — the list-screen shape test."""
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(self.client.get(url).status_code, 200)
        return len(captured)

    def completed_project(self):
        return Project.objects.create(
            name="ZQ Finished tower", bua_sqft=D("18000"), status=Project.Status.COMPLETED)


# ------------------------------------------------------------- the status
class TheStatusIsDerived(DrawingsCase):
    """⚠ NOBODY TYPES A STATUS. It is worked out from the newest revision."""

    def test_no_revision_is_required(self):
        self.assertEqual(self.drawing.status, status.REQUIRED)

    def test_a_revision_not_approved_is_received(self):
        self.revision()
        self.assertEqual(self.drawing.status, status.RECEIVED)

    def test_an_approved_newest_revision_is_approved(self):
        self.revision().approve(self.user)
        self.assertEqual(self.drawing.status, status.APPROVED)

    def test_a_newer_revision_supersedes_an_approved_one(self):
        """⚠ The paper on site is no longer the paper that was approved."""
        self.revision(label="R0").approve(self.user)
        self.revision(label="R1")
        self.assertEqual(self.drawing.status, status.RECEIVED)
        self.assertEqual(self.drawing.latest_revision.label, "R1")

    def test_the_bulk_helper_agrees_with_the_property(self):
        second = Drawing.objects.create(project=self.project, group=self.str_,
                                        number="ZQ-S-001", title="Footings")
        self.revision(label="R0").approve(self.user)
        self.revision(second, label="R0")
        third = Drawing.objects.create(project=self.project, group=self.str_,
                                       number="ZQ-S-002", title="Columns")
        rows = status.rows_for([self.drawing, second, third])
        self.assertEqual([row["state"] for row in rows],
                         [status.APPROVED, status.RECEIVED, status.REQUIRED])
        self.assertEqual(status.summarise(rows),
                         {"counts": {"required": 1, "received": 1, "approved": 1},
                          "total": 3, "required": 1, "received": 1, "approved": 1})

    def test_the_five_types_are_seeded_in_order_and_the_old_two_are_retired(self):
        """The owner's five: Architect, Structure, Survey, Passing, MEP. LND and INT stay, off."""
        self.assertEqual(list(DrawingGroup.objects.filter(is_active=True)
                              .values_list("code", "name", "sort_order")),
                         [("ARC", "Architect", 10), ("STR", "Structure", 20),
                          ("SUR", "Survey", 30), ("PAS", "Passing", 40), ("MEP", "MEP", 50)])
        self.assertEqual(set(DrawingGroup.objects.filter(is_active=False)
                             .values_list("code", flat=True)), {"LND", "INT"})


# ------------------------------------------------------------- the rules
class NothingIsOverwrittenOrDeleted(DrawingsCase):

    def test_a_label_is_unique_per_drawing_at_the_database(self):
        self.revision(label="R0")
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                self.revision(label="R0")
        # The same label on another drawing is fine.
        second = Drawing.objects.create(project=self.project, group=self.arc,
                                        number="ZQ-A-102", title="First floor")
        self.revision(second, label="R0")

    def test_a_drawing_number_is_unique_per_project_only(self):
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Drawing.objects.create(project=self.project, group=self.arc,
                                       number="ZQ-A-101", title="Again")
        Drawing.objects.create(project=self.other, group=self.arc, number="ZQ-A-101", title="Other")

    def test_a_drawing_with_revisions_cannot_be_deleted(self):
        self.revision()
        with self.assertRaises(DrawingInUse):
            self.drawing.delete()
        self.assertTrue(Drawing.objects.filter(pk=self.drawing.pk).exists())

    def test_a_drawing_nothing_points_at_can_still_be_deleted(self):
        self.drawing.delete()
        self.assertFalse(Drawing.objects.filter(number="ZQ-A-101").exists())


class ApprovalIsRecordedOnce(DrawingsCase):

    def test_approving_records_who_and_when(self):
        revision = self.revision()
        revision.approve(self.user, on=date(2026, 9, 1))
        revision.refresh_from_db()
        self.assertEqual((revision.approved_by, revision.approved_on), (self.user, date(2026, 9, 1)))

    def test_a_second_approval_is_refused_and_the_first_stands(self):
        revision = self.revision()
        revision.approve(self.user, on=date(2026, 9, 1))
        someone = self.make_user("zq.pm", role=Role.PROJECT_MANAGER, name="Other Person")
        with self.assertRaises(ValueError):
            revision.approve(someone)
        revision.refresh_from_db()
        self.assertEqual((revision.approved_by, revision.approved_on), (self.user, date(2026, 9, 1)))

    def test_the_approve_screen_refuses_the_second_press(self):
        revision = self.revision()
        url = reverse("drawings_approve", args=[self.project.pk, revision.pk])
        self.client.post(url)
        revision.refresh_from_db()
        self.assertEqual(revision.approved_by, self.user)

        someone = self.make_user("zq.pm2", role=Role.PROJECT_MANAGER, name="Other Person")
        self.client.force_login(someone)
        response = self.client.post(url, follow=True)
        self.assertIn("already approved", response.content.decode())
        revision.refresh_from_db()
        self.assertEqual(revision.approved_by, self.user)

    def test_approving_is_scoped_to_the_project(self):
        revision = self.revision()
        response = self.client.post(
            reverse("drawings_approve", args=[self.other.pk, revision.pk]))
        self.assertEqual(response.status_code, 404)
        revision.refresh_from_db()
        self.assertIsNone(revision.approved_on)


# ------------------------------------------------------------- the screens
class TheOverview(DrawingsCase):

    def compliance_document(self, project):
        kind = ComplianceType.objects.create(code="ZQAMC", name="ZQ AMC")
        title = ComplianceTitle.objects.create(type=kind, name="ZQ Plan passing")
        item = ComplianceItem.objects.create(title=title, name="ZQ Rajachitthi")
        return ComplianceDocument.objects.create(
            project=project, item=item, file=a_pdf(), original_name="ZQ-raja.pdf")

    def test_it_counts_per_project_and_shows_the_latest_revision_date(self):
        self.revision(received_on=date(2026, 8, 20)).approve(self.user)
        Drawing.objects.create(project=self.project, group=self.str_, number="ZQ-S-1", title="Footings")
        body = self.client.get(reverse("drawings_home")).content.decode()
        self.assertIn("ZQ Bhudarpura", body)
        self.assertIn("ZQ Other site", body)
        self.assertIn("20/08/2026", body)
        self.assertIn("Latest revision", body)
        self.assertNotIn("transmittal", body.lower())

    def test_live_sites_and_completed_projects_are_two_sections(self):
        """A finished building's file is kept and shown, but never mistaken for a live site."""
        done = self.completed_project()
        Drawing.objects.create(project=done, group=self.arc, number="ZQ-OLD-1", title="As built")
        response = self.client.get(reverse("drawings_home"))
        self.assertEqual([row["project"] for row in response.context["live"]],
                         [self.project, self.other])
        self.assertEqual([row["project"] for row in response.context["completed"]], [done])
        body = response.content.decode()
        self.assertIn("Live sites", body)
        self.assertIn("Completed projects", body)
        self.assertIn("ZQ Finished tower", body)

    def test_each_row_counts_the_projects_compliance_documents_and_links_to_them(self):
        done = self.completed_project()
        self.compliance_document(done)
        response = self.client.get(reverse("drawings_home"))
        by_project = {row["project"]: row["compliance"]
                      for row in response.context["live"] + response.context["completed"]}
        self.assertEqual(by_project[done], 1)
        self.assertEqual(by_project[self.project], 0)
        self.assertIn(reverse("compliance_project", args=[done.pk]), response.content.decode())

    def test_a_draft_quoted_or_lost_project_is_not_listed(self):
        for status_ in (Project.Status.DRAFT, Project.Status.QUOTED, Project.Status.LOST):
            Project.objects.create(name=f"ZQ {status_}", bua_sqft=D("1000"), status=status_)
        response = self.client.get(reverse("drawings_home"))
        listed = {row["project"].name for row in response.context["live"] + response.context["completed"]}
        self.assertEqual(listed, {"ZQ Bhudarpura", "ZQ Other site"})

    def test_the_query_count_does_not_grow_with_drawings_or_projects(self):
        for i in range(3):
            self.revision(Drawing.objects.create(project=self.project, group=self.arc,
                                                 number=f"ZQ-N-{i}", title="x"))
        small = self.queries_for(reverse("drawings_home"))
        for i in range(20):
            drawing = Drawing.objects.create(project=self.other, group=self.str_,
                                             number=f"ZQ-M-{i}", title="y")
            self.revision(drawing)
        for i in range(5):
            done = Project.objects.create(name=f"ZQ Done {i}", bua_sqft=D("1000"),
                                          status=Project.Status.COMPLETED)
            self.revision(Drawing.objects.create(project=done, group=self.arc,
                                                 number=f"ZQ-D-{i}", title="z"))
            self.compliance_document(done) if i == 0 else None
        big = self.queries_for(reverse("drawings_home"))
        self.assertLess(big - small, 10)


class ACompletedProjectStillAcceptsFiles(DrawingsCase):
    """⚠ THE POINT OF THE REPOSITORY: filing an old project's drawings after the fact."""

    def setUp(self):
        super().setUp()
        self.done = self.completed_project()

    def test_the_register_opens_and_offers_the_completed_project_in_the_picker(self):
        response = self.client.get(reverse("drawings_register", args=[self.done.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.done, response.context["projects"])

    def test_a_drawing_can_be_registered_and_a_revision_uploaded(self):
        self.client.post(reverse("drawings_new", args=[self.done.pk]), {
            "number": "ZQ-AB-1", "title": "As-built ground floor", "group": self.arc.pk})
        drawing = Drawing.objects.get(project=self.done, number="ZQ-AB-1")
        self.client.post(reverse("drawings_upload", args=[self.done.pk, drawing.pk]),
                         {"file": a_pdf(), "label": "R0", "received_on": "2024-03-01"})
        self.assertEqual(drawing.revisions.get().received_on, date(2024, 3, 1))

    def test_the_passing_type_is_offered_on_the_form(self):
        response = self.client.get(reverse("drawings_new", args=[self.done.pk]))
        self.assertEqual([g.code for g in response.context["groups"]],
                         ["ARC", "STR", "SUR", "PAS", "MEP"])


class TheRegister(DrawingsCase):

    def setUp(self):
        super().setUp()
        self.footing = Drawing.objects.create(project=self.project, group=self.str_,
                                              number="ZQ-S-001", title="Footings")
        self.revision(self.footing)

    def test_it_is_grouped_and_pilled(self):
        body = self.client.get(reverse("drawings_register", args=[self.project.pk])).content.decode()
        self.assertIn("ARC — Architect", body)
        self.assertIn("STR — Structure", body)
        self.assertIn("ZQ-A-101", body)
        self.assertIn("Required", body)
        self.assertIn("Received", body)

    def test_it_filters_by_group_and_status(self):
        url = reverse("drawings_register", args=[self.project.pk])
        body = self.client.get(url + "?group=STR").content.decode()
        self.assertIn("ZQ-S-001", body)
        self.assertNotIn("ZQ-A-101", body)
        body = self.client.get(url + "?status=required").content.decode()
        self.assertIn("ZQ-A-101", body)
        self.assertNotIn("ZQ-S-001", body)

    def test_it_only_shows_this_projects_drawings(self):
        Drawing.objects.create(project=self.other, group=self.arc, number="ZQ-ELSE", title="No")
        body = self.client.get(reverse("drawings_register", args=[self.project.pk])).content.decode()
        self.assertNotIn("ZQ-ELSE", body)

    def test_the_default_address_opens_the_first_live_project(self):
        response = self.client.get(reverse("drawings_register_default"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("ZQ-A-101", response.content.decode())

    def test_the_query_count_does_not_grow_with_rows(self):
        url = reverse("drawings_register", args=[self.project.pk])
        small = self.queries_for(url)
        for i in range(20):
            drawing = Drawing.objects.create(project=self.project, group=self.arc,
                                             number=f"ZQ-R-{i}", title="x", architect=self.architect)
            self.revision(drawing).approve(self.user)
        big = self.queries_for(url)
        self.assertLess(big - small, 10)

    def test_the_upload_button_is_not_drawn_for_a_site_engineer(self):
        self.client.force_login(self.make_user("zq.site", role=Role.SITE))
        body = self.client.get(reverse("drawings_register", args=[self.project.pk])).content.decode()
        self.assertNotIn("Upload revision", body)
        self.assertNotIn("Register a drawing", body)


class RegisteringADrawing(DrawingsCase):

    def test_the_form_registers_one(self):
        response = self.client.post(reverse("drawings_new", args=[self.project.pk]), {
            "number": "ZQ-A-102", "title": "First floor plan", "group": self.arc.pk,
            "architect": self.architect.pk, "required_by": "2026-10-01"})
        drawing = Drawing.objects.get(number="ZQ-A-102")
        self.assertRedirects(response, reverse("drawings_detail", args=[self.project.pk, drawing.pk]))
        self.assertEqual((drawing.project, drawing.required_by, drawing.created_by),
                         (self.project, date(2026, 10, 1), self.user))

    def test_a_duplicate_number_is_refused(self):
        self.client.post(reverse("drawings_new", args=[self.project.pk]), {
            "number": "zq-a-101", "title": "Again", "group": self.arc.pk})
        self.assertEqual(Drawing.objects.filter(project=self.project).count(), 1)

    def test_editing_can_deactivate_but_never_delete(self):
        self.revision()
        self.client.post(reverse("drawings_edit", args=[self.project.pk, self.drawing.pk]), {
            "number": "ZQ-A-101", "title": "Ground floor plan", "group": self.arc.pk})
        self.drawing.refresh_from_db()
        self.assertFalse(self.drawing.is_active)
        self.assertEqual(self.drawing.revisions.count(), 1)

    def test_editing_is_scoped_to_the_project(self):
        response = self.client.get(reverse("drawings_edit", args=[self.other.pk, self.drawing.pk]))
        self.assertEqual(response.status_code, 404)

    def test_bulk_registers_every_line_under_one_group(self):
        response = self.client.post(reverse("drawings_bulk", args=[self.project.pk]), {
            "group": self.str_.pk,
            "lines": "ZQ-S-001 | Footings\n\n ZQ-S-002|Columns \n"})
        self.assertRedirects(response, reverse("drawings_register", args=[self.project.pk]))
        self.assertEqual(list(Drawing.objects.filter(group=self.str_, project=self.project)
                              .order_by("number").values_list("number", "title")),
                         [("ZQ-S-001", "Footings"), ("ZQ-S-002", "Columns")])

    def test_bulk_is_all_or_nothing(self):
        self.client.post(reverse("drawings_bulk", args=[self.project.pk]), {
            "group": self.str_.pk,
            "lines": "ZQ-S-001 | Footings\nno bar here\nZQ-A-101 | duplicate"})
        self.assertFalse(Drawing.objects.filter(number="ZQ-S-001").exists())


class OneDrawing(DrawingsCase):

    def test_the_detail_lists_every_revision(self):
        r0 = self.revision(label="R0")
        r0.approve(self.user)
        self.revision(label="R1")
        body = self.client.get(
            reverse("drawings_detail", args=[self.project.pk, self.drawing.pk])).content.decode()
        self.assertIn("R0", body)
        self.assertIn("R1", body)
        self.assertIn("Received", body)
        self.assertNotIn("Sent to", body)

    def test_it_is_scoped_to_the_project(self):
        response = self.client.get(reverse("drawings_detail", args=[self.other.pk, self.drawing.pk]))
        self.assertEqual(response.status_code, 404)

    def test_the_query_count_does_not_grow_with_revisions(self):
        url = reverse("drawings_detail", args=[self.project.pk, self.drawing.pk])
        self.revision(label="R0")
        small = self.queries_for(url)
        for i in range(1, 21):
            self.revision(label=f"R{i}")
        big = self.queries_for(url)
        self.assertLess(big - small, 10)


class UploadingARevision(DrawingsCase):

    def test_an_upload_is_a_new_row_and_keeps_the_old_one(self):
        self.upload(label="R0")
        self.upload(label="R1")
        labels = list(self.drawing.revisions.values_list("label", flat=True))
        self.assertEqual(labels, ["R1", "R0"])
        first = self.drawing.revisions.get(label="R0")
        self.assertEqual((first.original_name, first.uploaded_by), ("ZQ-plan.pdf", self.user))
        self.assertGreater(first.size_bytes, 0)

    def test_a_repeated_label_is_refused(self):
        self.upload(label="R0")
        response = self.upload(label="r0", follow=True)
        self.assertEqual(self.drawing.revisions.count(), 1)
        self.assertIn("already has a revision", response.content.decode())

    def test_an_executable_is_refused(self):
        self.client.post(reverse("drawings_upload", args=[self.project.pk, self.drawing.pk]), {
            "file": SimpleUploadedFile("nasty.exe", b"MZ", content_type="application/exe"),
            "label": "R0"})
        self.assertFalse(DrawingRevision.objects.exists())

    def test_a_cad_file_is_accepted(self):
        self.client.post(reverse("drawings_upload", args=[self.project.pk, self.drawing.pk]), {
            "file": SimpleUploadedFile("plan.dwg", b"AC1027", content_type="application/octet-stream"),
            "label": "R0", "received_on": "2026-09-01"})
        self.assertEqual(DrawingRevision.objects.get().received_on, date(2026, 9, 1))

    def test_a_new_upload_after_approval_puts_the_drawing_back_to_received(self):
        self.upload(label="R0")
        self.drawing.revisions.get().approve(self.user)
        response = self.upload(label="R1", follow=True)
        self.assertEqual(self.drawing.status, status.RECEIVED)
        self.assertIn("superseded", response.content.decode())

    def test_the_upload_is_scoped_to_the_project(self):
        response = self.client.post(
            reverse("drawings_upload", args=[self.other.pk, self.drawing.pk]),
            {"file": a_pdf(), "label": "R0"})
        self.assertEqual(response.status_code, 404)


class TheFileIsOnlyReachableThroughTheView(DrawingsCase):

    def test_download_hands_over_the_file_as_an_attachment(self):
        revision = self.revision()
        response = self.client.get(reverse("drawings_download", args=[revision.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn("R0.pdf", response["Content-Disposition"])
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4 not really a pdf")

    def test_a_missing_file_is_a_404_not_a_crash(self):
        revision = self.revision()
        revision.file.storage.delete(revision.file.name)
        response = self.client.get(reverse("drawings_download", args=[revision.pk]))
        self.assertEqual(response.status_code, 404)

    def test_every_earlier_revision_stays_downloadable(self):
        r0 = self.revision(label="R0")
        self.revision(label="R1")
        self.assertEqual(self.client.get(reverse("drawings_download", args=[r0.pk])).status_code, 200)

    def test_there_is_no_media_url(self):
        # ⚠ settings.MEDIA_URL reads back as "/" when unset — Django prefixes the
        #   script name — so the proof is the address, not the setting.
        revision = self.revision()
        self.assertEqual(self.client.get("/media/" + revision.file.name).status_code, 404)
        self.assertEqual(self.client.get("/" + revision.file.name).status_code, 404)

    def test_an_accountant_cannot_download(self):
        revision = self.revision()
        self.client.force_login(self.make_user("zq.acc", role=Role.ACCOUNTANT))
        self.assertEqual(self.client.get(reverse("drawings_download", args=[revision.pk])).status_code, 403)

    def test_a_site_engineer_may_download_and_may_not_upload(self):
        revision = self.revision()
        self.client.force_login(self.make_user("zq.mistry", role=Role.SITE))
        self.assertEqual(self.client.get(reverse("drawings_download", args=[revision.pk])).status_code, 200)
        self.assertEqual(self.upload(label="R1").status_code, 403)


class WhoMayDoWhat(DrawingsCase):

    def test_four_roles_may_read_and_two_may_not(self):
        for role in (Role.ADMIN, Role.PROJECT_MANAGER, Role.PURCHASE, Role.SITE):
            self.client.force_login(self.make_user(f"zq.{role}.r", role=role))
            self.assertEqual(self.client.get(reverse("drawings_home")).status_code, 200, role)
        for role in (Role.ACCOUNTANT, Role.COMPLIANCE):
            self.client.force_login(self.make_user(f"zq.{role}.r", role=role))
            self.assertEqual(self.client.get(reverse("drawings_home")).status_code, 403, role)

    def test_only_admin_and_project_manager_may_edit(self):
        for role, allowed in [(Role.ADMIN, True), (Role.PROJECT_MANAGER, True),
                              (Role.PURCHASE, False), (Role.SITE, False), (Role.ACCOUNTANT, False)]:
            self.client.force_login(self.make_user(f"zq.{role}.e", role=role))
            response = self.client.get(reverse("drawings_new", args=[self.project.pk]))
            self.assertEqual(response.status_code != 403, allowed, role)

    def test_there_is_no_transmittal_screen_or_permission(self):
        from accounts.perms import MATRIX
        from django.urls import NoReverseMatch
        self.assertNotIn("drawings.transmit", MATRIX)
        with self.assertRaises(NoReverseMatch):
            reverse("drawings_transmittals", args=[self.project.pk])

    def test_writes_are_post_only(self):
        revision = self.revision()
        self.assertEqual(self.client.get(
            reverse("drawings_approve", args=[self.project.pk, revision.pk])).status_code, 405)
        self.assertEqual(self.client.get(
            reverse("drawings_upload", args=[self.project.pk, self.drawing.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse("drawings_groups_save")).status_code, 405)


# ------------------------------------------------------------- the masters
class Architects(DrawingsCase):

    def test_the_list_counts_drawings(self):
        body = self.client.get(reverse("drawings_architects")).content.decode()
        self.assertIn("ZQ Architect", body)
        self.assertIn("ZQ Studio", body)

    def test_adding_keeps_digits_only(self):
        self.client.post(reverse("drawings_architect_new"), {
            "name": "ZQ New", "firm": "ZQ Firm", "phone": "+91 98250 00000", "email": "a@zq.in"})
        self.assertEqual(Architect.objects.get(name="ZQ New").phone, "919825000000")

    def test_a_duplicate_name_is_refused(self):
        self.client.post(reverse("drawings_architect_new"), {"name": "zq architect"})
        self.assertEqual(Architect.objects.filter(name__iexact="ZQ Architect").count(), 1)

    def test_editing_can_deactivate_and_the_drawings_keep_the_name(self):
        self.client.post(reverse("drawings_architect_edit", args=[self.architect.pk]), {
            "name": "ZQ Architect", "firm": "ZQ Studio", "phone": "9900000001"})
        self.architect.refresh_from_db()
        self.assertFalse(self.architect.is_active)
        self.drawing.refresh_from_db()
        self.assertEqual(self.drawing.architect, self.architect)

    def test_a_purchase_person_may_read_and_may_not_edit(self):
        self.client.force_login(self.make_user("zq.pur", role=Role.PURCHASE))
        self.assertEqual(self.client.get(reverse("drawings_architects")).status_code, 200)
        self.assertEqual(self.client.get(reverse("drawings_architect_new")).status_code, 403)


class Groups(DrawingsCase):

    def post(self, **fields):
        data = {}
        for group in DrawingGroup.objects.all():
            data[f"row-{group.id}"] = "1"
            data[f"code-{group.id}"] = group.code
            data[f"name-{group.id}"] = group.name
            data[f"sort_order-{group.id}"] = str(group.sort_order)
            if group.is_active:
                data[f"is_active-{group.id}"] = "on"
        data.update(fields)
        return self.client.post(reverse("drawings_groups_save"), data)

    def test_the_screen_renders_every_group_with_its_count(self):
        body = self.client.get(reverse("drawings_groups")).content.decode()
        for code in ("ARC", "STR", "SUR", "PAS", "MEP", "LND", "INT"):
            self.assertIn(code, body)

    def test_a_row_is_edited_in_place(self):
        self.post(**{f"name-{self.arc.id}": "Architecture", f"sort_order-{self.arc.id}": "15"})
        self.arc.refresh_from_db()
        self.assertEqual((self.arc.name, self.arc.sort_order), ("Architecture", 15))

    def test_the_blank_row_adds_one_and_the_code_is_uppercased(self):
        self.post(**{"new-code": "fire", "new-name": "Fire fighting"})
        self.assertTrue(DrawingGroup.objects.filter(code="FIRE", name="Fire fighting").exists())

    def test_a_row_missing_its_marker_is_left_alone(self):
        """>>> ANCHOR: MASTER-TABS <<< — an absent checkbox is not a cleared one."""
        data = {"new-code": "", f"row-{self.arc.id}": "1", f"code-{self.arc.id}": "ARC",
                f"name-{self.arc.id}": "Architect", f"sort_order-{self.arc.id}": "10"}
        self.client.post(reverse("drawings_groups_save"), data)
        self.arc.refresh_from_db()
        self.str_.refresh_from_db()
        self.assertFalse(self.arc.is_active)
        self.assertTrue(self.str_.is_active)

    def test_a_group_is_never_deleted(self):
        self.post(**{f"is_active-{self.arc.id}": ""})
        self.assertEqual(DrawingGroup.objects.count(), 7)

    def test_a_duplicate_code_is_refused(self):
        self.post(**{"new-code": "arc", "new-name": "Again"})
        self.assertEqual(DrawingGroup.objects.filter(code="ARC").count(), 1)


# ------------------------------------------------------------- the panels
class ThePanelsKeepTheFormat(TestCase):
    """The same rules projects/test_info_panels.py enforces, applied before wiring."""

    KEYS = {"drawings_home", "drawings_register", "drawings_form", "drawings_bulk",
            "drawings_detail", "drawings_architects", "drawings_groups"}

    def test_every_screen_has_a_panel(self):
        self.assertEqual(set(PANELS), self.KEYS)

    def test_the_rules(self):
        for key, panel in PANELS.items():
            with self.subTest(panel=key):
                self.assertTrue(panel["title"])
                self.assertGreaterEqual(len(panel["steps"]), 3)
            for step in panel["steps"]:
                with self.subTest(panel=key, step=step["label"]):
                    words = len(step["text"].split())
                    self.assertGreaterEqual(words, 18)
                    self.assertLessEqual(words, 32)
                    self.assertLessEqual(len(step["label"].split()), 2)
                    self.assertNotIn("<", step["text"])
                    for control in re.findall(r"\[\[(.+?)\]\]", step["text"]):
                        self.assertLessEqual(len(control.split()), 4)


class NoTemplateLeaksASyntaxTag(DrawingsCase):

    def test_every_screen_renders_clean(self):
        self.revision()
        urls = [
            reverse("drawings_home"),
            reverse("drawings_register", args=[self.project.pk]),
            reverse("drawings_new", args=[self.project.pk]),
            reverse("drawings_bulk", args=[self.project.pk]),
            reverse("drawings_edit", args=[self.project.pk, self.drawing.pk]),
            reverse("drawings_detail", args=[self.project.pk, self.drawing.pk]),
            reverse("drawings_architects"),
            reverse("drawings_architect_new"),
            reverse("drawings_architect_edit", args=[self.architect.pk]),
            reverse("drawings_groups"),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                body = response.content.decode()
                for leak in ("{#", "#}", "{%", "%}"):
                    self.assertNotIn(leak, body)
