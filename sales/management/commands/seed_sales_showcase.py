"""
Sales demo data on top of `seed_showcase`: units, enquiries, bookings, demand
letters and receipts on the three "Showcase — …" projects.

HOW TO RUN IT
    python manage.py seed_showcase              first — this needs its projects
    python manage.py seed_sales_showcase        then this
    python manage.py seed_sales_showcase --remove

⚠ IT REFUSES TO RUN WITHOUT THE SHOWCASE PROJECTS, and it does nothing to a
    project that is not one of them. Everything it makes is found again through
    the projects' names, plus customer phones starting 98000 — so `--remove`
    takes away exactly what was made and nothing else.

⚠ `seed_showcase --remove` DELETES ITS PROJECTS, and a unit PROTECTS its
    project. Run THIS command's `--remove` first, or that one refuses.
"""
import random
from datetime import timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from projects.models import Project
from sales import services
from sales.models import (
    Booking, BookingEvent, Customer, CustomerReceipt, Demand, Enquiry, EnquirySource,
    PaymentMilestone, SiteVisit, Unit, UnitKind,
)
from tasks.models import TaskHeader

MARK = "Showcase — "
PHONE_PREFIX = "98000"

NAMES = [
    "Ramesh Patel", "Hetal Shah", "Kiran Mehta", "Bhavna Desai", "Nilesh Joshi",
    "Priya Trivedi", "Mahesh Parikh", "Anita Bhatt", "Sanjay Dave", "Meera Gandhi",
    "Rakesh Modi", "Falguni Vyas", "Dinesh Soni", "Jigna Thakkar", "Paresh Amin",
    "Rupal Panchal", "Vipul Raval", "Kajal Nayak", "Ashok Pandya", "Sonal Doshi",
]
BROKERS = ["Shree Estate", "Skyline Realty", "Om Properties"]


class Command(BaseCommand):
    help = "Units, enquiries, bookings, demands and receipts on the showcase projects."

    def add_arguments(self, parser):
        parser.add_argument("--remove", action="store_true", help="Take the sales demo data away.")

    def handle(self, *args, **options):
        projects = list(Project.objects.filter(name__startswith=MARK).order_by("id"))
        if options["remove"]:
            return self.remove(projects)
        if not projects:
            self.stderr.write("No showcase projects. Run `python manage.py seed_showcase` first.")
            return
        if Unit.objects.filter(project__in=projects).exists():
            self.stderr.write("Sales showcase data already exists. Use --remove first.")
            return
        random.seed(7)
        with transaction.atomic():
            self.build(projects)

    # ---------------------------------------------------------------- build
    def build(self, projects):
        User = get_user_model()
        by = User.objects.filter(is_active=True).order_by("id").first()
        today = timezone.localdate()
        made = {"units": 0, "enquiries": 0, "bookings": 0, "demands": 0, "receipts": 0}
        name_index = 0

        for number, project in enumerate(projects, 1):
            floors = 5 + number * 2
            per_floor = 4
            kinds = [UnitKind.TWO_BHK, UnitKind.THREE_BHK, UnitKind.TWO_BHK, UnitKind.THREE_BHK]
            units = []
            for floor in range(1, floors + 1):
                for position in range(1, per_floor + 1):
                    kind = kinds[position - 1]
                    sqft = D("1150") if kind == UnitKind.TWO_BHK else D("1650")
                    units.append(Unit.objects.create(
                        project=project, number=f"A-{floor}{position:02d}", block="A", floor=floor,
                        kind=kind, carpet_sqft=sqft * D("0.8"), saleable_sqft=sqft,
                        base_price=sqft * D("4200") + D(floor) * D("25000")))
            made["units"] += len(units)

            headers = list(TaskHeader.objects.filter(project=project).order_by("start", "id"))
            slab_headers = [h for h in headers if "slab" in h.name.lower()] or headers[:3]

            # Bookings on roughly 40% of units, spread across five months.
            sold = units[: int(len(units) * 0.4)]
            for offset, unit in enumerate(sold):
                name = NAMES[name_index % len(NAMES)]
                name_index += 1
                phone = f"{PHONE_PREFIX}{name_index:05d}"
                booked_on = today - timedelta(days=150 - offset * 9)
                enquiry = Enquiry.objects.create(
                    project=project, name=name, phone=phone,
                    source=random.choice(EnquirySource.values),
                    interested_in=unit.kind, budget=unit.base_price, assigned_to=by,
                    stage=Enquiry.Stage.NEGOTIATING)
                SiteVisit.objects.create(enquiry=enquiry, visited_on=booked_on - timedelta(days=7),
                                         note="Saw the sample flat", recorded_by=by)
                made["enquiries"] += 1
                schedule = [{"name": n, "percent": p} for n, p in services.calc.DEFAULT_SCHEDULE]
                for index, header in enumerate(slab_headers[:3]):
                    schedule[3 + index]["task_header"] = header
                booking = services.book_unit(
                    unit, phone=phone, name=name, email="", pan="",
                    address=f"{random.randint(2, 48)}, Satellite, Ahmedabad",
                    agreement_value=unit.base_price, gst_percent=D("5"),
                    booked_on=booked_on, schedule=schedule, enquiry=enquiry, by=by)
                made["bookings"] += 1

                milestones = list(booking.milestones.order_by("sequence"))
                # Raise the first few demands, with receipts that leave a mix of
                # paid, part-paid, open and overdue letters.
                raised = 2 + (offset % 4)
                for step, milestone in enumerate(milestones[:raised]):
                    raised_on = booked_on + timedelta(days=step * 30)
                    if raised_on > today:
                        break
                    demand = services.raise_demand(
                        booking, milestone, raised_on=raised_on,
                        due_on=raised_on + timedelta(days=15), by=by)
                    made["demands"] += 1
                    total = services.calc.demand_total(demand)
                    tds = services.calc.suggested_tds(booking, total)
                    if step < raised - 1 or offset % 3 == 0:
                        amount = total - tds if offset % 5 else (total - tds) / 2
                        services.record_receipt(
                            booking, amount=services.calc._money(amount),
                            received_on=min(raised_on + timedelta(days=10), today),
                            mode=random.choice(["neft", "cheque", "upi"]),
                            reference=f"UTR{random.randint(100000, 999999)}", tds_amount=tds,
                            demand=demand, by=by)
                        made["receipts"] += 1
                if offset % 4 == 1:
                    services.mark_agreement(booking, on=booked_on + timedelta(days=20), by=by)
                if offset % 7 == 3:
                    services.mark_registered(booking, on=booked_on + timedelta(days=45), by=by)

            # One cancellation, so the grid shows the word.
            if len(sold) > 5:
                victim = (Booking.objects.filter(unit=sold[5])
                          .exclude(status__in=[Booking.Status.REGISTERED, Booking.Status.CANCELLED]).first())
                if victim:
                    services.cancel_booking(victim, reason="Loan not sanctioned",
                                            deduction_pct=D("2"), by=by)

            # Open enquiries at every stage.
            for index in range(8):
                name = NAMES[name_index % len(NAMES)]
                name_index += 1
                stage = [Enquiry.Stage.NEW, Enquiry.Stage.VISITED, Enquiry.Stage.NEGOTIATING,
                         Enquiry.Stage.LOST][index % 4]
                enquiry = Enquiry.objects.create(
                    project=project, name=name, phone=f"{PHONE_PREFIX}{name_index:05d}",
                    source=EnquirySource.BROKER if index % 3 == 0 else EnquirySource.PORTAL,
                    broker_name=random.choice(BROKERS) if index % 3 == 0 else "",
                    interested_in=random.choice([UnitKind.TWO_BHK, UnitKind.THREE_BHK]),
                    budget=D("5500000"), assigned_to=by, stage=stage,
                    lost_reason="Bought elsewhere" if stage == Enquiry.Stage.LOST else "")
                if stage != Enquiry.Stage.NEW:
                    SiteVisit.objects.create(enquiry=enquiry, visited_on=today - timedelta(days=index),
                                             recorded_by=by)
                made["enquiries"] += 1

        self.stdout.write(self.style.SUCCESS("Sales showcase data created."))
        for label, count in made.items():
            self.stdout.write(f"  {count} {label}")

    # --------------------------------------------------------------- remove
    def remove(self, projects):
        counts = {}
        bookings = Booking.objects.filter(unit__project__in=projects)
        counts["receipts"] = CustomerReceipt.objects.filter(booking__in=bookings).count()
        CustomerReceipt.objects.filter(booking__in=bookings).delete()
        counts["demands"] = Demand.objects.filter(booking__in=bookings).count()
        Demand.objects.filter(booking__in=bookings).delete()
        PaymentMilestone.objects.filter(booking__in=bookings).delete()
        BookingEvent.objects.filter(booking__in=bookings).delete()
        counts["bookings"] = bookings.count()
        bookings.delete()
        counts["enquiries"] = Enquiry.objects.filter(project__in=projects).count()
        Enquiry.objects.filter(project__in=projects).delete()
        counts["units"] = Unit.objects.filter(project__in=projects).count()
        Unit.objects.filter(project__in=projects).delete()
        customers = Customer.objects.filter(phone__startswith=PHONE_PREFIX, bookings__isnull=True,
                                            bookings_transferred_away__isnull=True)
        counts["customers"] = customers.count()
        customers.delete()
        self.stdout.write(self.style.SUCCESS("Sales showcase data removed."))
        for label, number in counts.items():
            self.stdout.write(f"  {number} {label}")
