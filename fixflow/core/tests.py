"""Automated tests: run with  python manage.py test"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Notification, Profile, RepairRequest, Shop, Status


def next_weekday_slot(hour=10, days=2):
    """A valid drop-off time: some day soon, not Sunday, inside opening hours."""
    d = timezone.localtime() + timedelta(days=days)
    while d.weekday() == 6:
        d += timedelta(days=1)
    return d.replace(hour=hour, minute=0, second=0, microsecond=0)


class FlowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password="pw12345pw")
        Profile.objects.create(user=self.owner, role="shop", phone="9876543210")
        self.shop = Shop.objects.create(owner=self.owner, name="FixIt", address="x", phone="9876543210",
                                        device_types="phone,speaker", express_fee=200, slots_per_hour=1)
        self.cust = User.objects.create_user("cust", password="pw12345pw")
        Profile.objects.create(user=self.cust, role="customer", phone="9123456780")
        self.other = User.objects.create_user("other", password="pw12345pw")
        Profile.objects.create(user=self.other, role="customer", phone="9000000000")

    def book(self, **over):
        self.client.login(username="cust", password="pw12345pw")
        data = {"device_type": "speaker", "device_name": "JBL Go", "problem": "No sound",
                "drop_slot": next_weekday_slot().strftime("%Y-%m-%dT%H:%M")}
        data.update(over)
        return self.client.post(reverse("shop_detail", args=[self.shop.pk]), data)

    def make_job(self, status=Status.PENDING, **kw):
        return RepairRequest.objects.create(customer=self.cust, shop=self.shop, device_type="speaker",
                                            device_name="JBL", problem="x", drop_slot=next_weekday_slot(),
                                            status=status, **kw)

    def act(self, user, job, action, **post):
        self.client.login(username=user, password="pw12345pw")
        return self.client.post(reverse("request_action", args=[job.pk, action]), post)

    def test_full_happy_path(self):
        self.book(express="on")
        job = RepairRequest.objects.get()
        self.assertEqual(job.express_fee, Decimal("200"))
        self.assertTrue(Notification.objects.filter(user=self.owner).exists())
        self.act("owner", job, "accept")
        self.act("owner", job, "receive")
        self.client.login(username="owner", password="pw12345pw")
        self.client.post(reverse("request_diagnose", args=[job.pk]), {"diagnosis": "Blown driver", "cost": "500", "days": "2"})
        job.refresh_from_db()
        self.assertEqual(job.status, Status.AWAITING_APPROVAL)
        self.act("cust", job, "approve")
        job.refresh_from_db()
        self.assertEqual(job.approved_cost, Decimal("500"))
        self.act("owner", job, "ready")
        self.act("owner", job, "complete")
        job.refresh_from_db()
        self.assertEqual(job.status, Status.COMPLETED)
        self.assertTrue(job.is_paid)
        self.assertEqual(job.total_price, Decimal("700"))

    def test_budget_auto_approves(self):
        job = self.make_job(Status.RECEIVED, max_budget=Decimal("600"))
        self.client.login(username="owner", password="pw12345pw")
        self.client.post(reverse("request_diagnose", args=[job.pk]), {"diagnosis": "Fan", "cost": "400", "days": "0"})
        job.refresh_from_db()
        self.assertEqual(job.status, Status.IN_REPAIR)

    def test_revised_quote_needs_new_approval(self):
        job = self.make_job(Status.IN_REPAIR, approved_cost=Decimal("400"), quoted_cost=Decimal("400"))
        self.client.login(username="owner", password="pw12345pw")
        self.client.post(reverse("request_diagnose", args=[job.pk]), {"diagnosis": "Worse than thought", "cost": "900", "days": "3"})
        job.refresh_from_db()
        self.assertEqual(job.status, Status.AWAITING_APPROVAL)

    def test_slot_capacity_and_rules(self):
        self.book()
        self.assertEqual(RepairRequest.objects.count(), 1)
        self.book()                                   # same hour, capacity is 1
        self.assertEqual(RepairRequest.objects.count(), 1)
        self.book(drop_slot=(timezone.localtime() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"))
        self.book(drop_slot=next_weekday_slot(hour=22, days=3).strftime("%Y-%m-%dT%H:%M"))
        self.assertEqual(RepairRequest.objects.count(), 1)

    def test_unsupported_device_and_express(self):
        self.book(device_type="tv")
        self.assertEqual(RepairRequest.objects.count(), 0)
        self.shop.express_fee = 0
        self.shop.save()
        self.book(express="on")
        self.assertEqual(RepairRequest.objects.count(), 0)

    def test_permissions_and_illegal_moves(self):
        job = self.make_job()
        self.assertEqual(self.act("other", job, "cancel").status_code, 404)    # stranger
        self.act("cust", job, "accept")                                        # customer can't accept
        job.refresh_from_db(); self.assertEqual(job.status, Status.PENDING)
        self.act("owner", job, "ready")                                        # can't skip steps
        job.refresh_from_db(); self.assertEqual(job.status, Status.PENDING)
        self.act("owner", job, "reject")                                       # reason required
        job.refresh_from_db(); self.assertEqual(job.status, Status.PENDING)
        self.act("owner", job, "reject", note="Parts unavailable")
        job.refresh_from_db(); self.assertEqual(job.status, Status.REJECTED)
        self.act("owner", job, "accept")                                       # finished jobs stay finished
        job.refresh_from_db(); self.assertEqual(job.status, Status.REJECTED)

    def test_decline_then_return(self):
        job = self.make_job(Status.AWAITING_APPROVAL, quoted_cost=Decimal("999"))
        self.act("cust", job, "decline")
        self.act("owner", job, "returned")
        job.refresh_from_db(); self.assertEqual(job.status, Status.RETURNED)

    def test_api_only_shows_own_requests(self):
        self.make_job()
        self.client.login(username="other", password="pw12345pw")
        self.assertEqual(len(self.client.get("/api/requests/").json()), 0)
        self.client.login(username="cust", password="pw12345pw")
        self.assertEqual(len(self.client.get("/api/requests/").json()), 1)
        self.assertEqual(self.client.get("/api/unread/").json(), {"unread": 0})
